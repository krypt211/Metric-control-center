"""Private-chat approvals with explicit user bindings and durable replay guards."""
import asyncio
import hashlib
import json
import os
from decimal import Decimal
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select, update

from services.actions.engine import ActionRejected
from services.storage.models import AIDecision, AgentMessage, TelegramCommand, TelegramCursor, User
from services.storage.repository import insert_for
from services.sync.engine import aware


class Binding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    telegram_user_id: int = Field(gt=0)
    chat_id: int = Field(gt=0)
    user_id: str = Field(min_length=1, max_length=36)

    @model_validator(mode="after")
    def private(self):
        if self.telegram_user_id != self.chat_id:
            raise ValueError("Only the user's private chat is supported")
        return self


class TelegramFailure(RuntimeError):
    pass


class TelegramAPI:
    def __init__(self, token, *, transport=None):
        if not token or ":" not in token or not token.split(":", 1)[0].isdigit():
            raise ValueError("Invalid bot token")
        self.token, self.transport = token, transport
        self.bot_id = token.split(":", 1)[0]

    async def call(self, method, payload):
        if method not in ("getUpdates", "sendMessage", "answerCallbackQuery", "editMessageText"):
            raise ValueError("Unsupported bot method")
        try:
            async with httpx.AsyncClient(timeout=35, follow_redirects=False, trust_env=False, transport=self.transport) as client:
                response = await client.post(f"https://api.telegram.org/bot{self.token}/{method}", json=payload)
            if response.status_code != 200 or response.json().get("ok") is not True:
                raise TelegramFailure("Telegram request failed")
            return response.json()["result"]
        except httpx.HTTPError:
            # httpx errors can include the token-bearing URL; never propagate it.
            raise TelegramFailure("Telegram network failure") from None


def review_text(view, *, reasons=True, truncate=True):
    rows = ["AI: предложения на проверку", f"Статус: {view['status']}",
        f"Действительно до: {view['expires_at']}", (view["summary"] or "")[:300]]
    scopes = {}
    for scope in view.get("command_scopes", {}).values():
        key = json.dumps({"query": scope["query"], "conditions": scope["conditions"]}, sort_keys=True)
        scopes[key] = scope
    for scope in scopes.values():
        q = scope["query"]
        rows.append(f"Фильтр: GEO={q['country'] or 'ALL'}, offer={q['offer'] or 'ALL'}, account={q['account_id'] or 'ALL'}, entity={q['entity_id'] or 'ALL'}, {q['currency']}, {q['window']}, {q['level']}, dates={scope['window']}, zone={scope['timezone']}\n"+
            " AND ".join(f"{c['metric']} {c['operator']} {c['value']}" for c in scope["conditions"]))
    if scopes:
        rows.append("Pause останавливает сущность целиком, включая другие GEO.")
        groups = {}
        for scope in view.get("command_scopes", {}).values():
            key = (scope["query"]["currency"], scope["timezone"])
            groups.setdefault(key, []).append(scope["metrics"]["spend"])
        rows.append("Найдено: "+str(len(view.get("command_scopes", {}))))
        for (currency, zone), values in groups.items():
            total = str(sum(Decimal(str(v)) for v in values)) if all(v is not None for v in values) else "неизвестно"
            rows.append(f"Текущие расходы: {total} {currency} ({zone})")
    explanations = []
    for index, item in enumerate(view["actions"], 1):
        p = item["proposal"]
        description = f"Budget {p['change_percent']:+g}% → {item['target_budget']}" if p["action"] == "budget_change" else p["action"]
        rows.append(f"{index}. {(item['entity_name'] or p['entity_id'])[:35]} ({p['entity_id']}): {description} [{item['status']}]")
        explanations.append(f"{index}. {p['reason'][:120]}" + (f" Policy: {item['policy_reason']}" if item["policy_reason"] else ""))
    if reasons: rows.extend(["Объяснения:", *explanations])
    # Plain text only: model text cannot create extra Telegram buttons or markup.
    text = "\n\n".join(rows)
    return text[:4000] if truncate else text


class ApprovalBot:
    def __init__(self, core, api, workspace, bindings):
        self.core, self.api, self.workspace = core, api, workspace
        self.bindings = [Binding.model_validate(b) for b in bindings]
        if len({b.telegram_user_id for b in self.bindings}) != len(self.bindings) or len({b.user_id for b in self.bindings}) != len(self.bindings):
            raise ValueError("Telegram bindings must be unique")
        self.scope = hashlib.sha256(f"{workspace}:{api.bot_id}".encode()).hexdigest()

    async def notify_next(self):
        now = self.core.clock()
        with self.core.sessions.begin() as session:
            decision = session.scalar(select(AIDecision).join(User, AIDecision.owner_id == User.id).where(AIDecision.workspace_id == self.workspace,
                User.workspace_id == self.workspace, User.role.in_(("admin", "operator")),
                AIDecision.owner_id.in_([b.user_id for b in self.bindings]),
                AIDecision.status == "pending", AIDecision.telegram_status.is_(None),
                AIDecision.expires_at > now).order_by(AIDecision.created_at).with_for_update(skip_locked=True).limit(1))
            if not decision:
                return None
            binding = next((b for b in self.bindings if b.user_id == decision.owner_id), None)
            if not binding:
                return None
            from services.ai.engine import authorize
            authorize(session, self.workspace, binding.user_id)
            claimed = session.execute(update(AIDecision).where(AIDecision.id == decision.id,
                AIDecision.telegram_status.is_(None)).values(telegram_status="attempting"))
            if claimed.rowcount != 1:
                return None
            identity, token = decision.id, decision.payload["callback_token"]
            view = self.core.view(session, decision)
        pending = sum(item["status"] == "pending" for item in view["actions"])
        buttons = [{"text": "REVIEW", "callback_data": "review:"+token}, {"text": "REJECT", "callback_data": "reject:"+token}]
        confirmation_fits = len(review_text(view, reasons=False, truncate=False)) <= 3500
        if pending and confirmation_fits:
            label = "CONFIRM" if view.get("requires_confirmation") else "APPROVE ALL"
            buttons.insert(0, {"text": f"{label} ({pending})", "callback_data": "approve:"+token})
        try:
            result = await self.api.call("sendMessage", {"chat_id": binding.chat_id, "text": review_text(view),
                "reply_markup": {"inline_keyboard": [[button] for button in buttons]}})
            with self.core.sessions.begin() as session:
                decision = session.get(AIDecision, identity)
                decision.telegram_status = "sent"
                decision.payload = {**decision.payload, "telegram": {"chat_id": binding.chat_id, "message_id": result["message_id"]}}
        except Exception:
            with self.core.sessions.begin() as session:
                session.get(AIDecision, identity).telegram_status = "unknown"
            # Sending is never automatically retried after an uncertain outcome.
        return identity

    def handle_message(self, update):
        message = update.get("message", {})
        sender, chat = message.get("from", {}).get("id"), message.get("chat", {})
        binding = next((b for b in self.bindings if b.telegram_user_id == sender and b.chat_id == chat.get("id")), None)
        if not binding or chat.get("type") != "private":
            raise ActionRejected("Telegram user is not authorized")
        text = message.get("text", "").strip()
        command_id = str(uuid5(NAMESPACE_URL, f"telegram:{self.scope}:{update['update_id']}"))
        with self.core.sessions.begin() as session:
            from services.ai.engine import authorize
            authorize(session, self.workspace, binding.user_id)
            existing = session.get(TelegramCommand, command_id)
            if existing and existing.status != "processing":
                return existing.payload["response"]
            if not existing:
                session.add(TelegramCommand(id=command_id, workspace_id=self.workspace, status="processing",
                    created_at=self.core.clock(), payload={"actor_id": binding.user_id, "operation": "message"}))
        try:
            if text.split(" ", 1)[0].split("@", 1)[0] == "/stop_auto":
                from services.automation.control import change
                change(self.core.sessions, self.workspace, binding.user_id, True, channel="telegram", clock=self.core.clock)
                response = "Emergency Stop: AI и rule actions выключены. Сбор статистики продолжается. Уже отправленные запросы отменить нельзя."
            elif os.environ.get("AI_ENABLED", "false").lower() != "true":
                raise ActionRejected("AI отключён. /stop_auto работает без подключения модели.")
            elif not text or text.startswith("/"):
                raise ActionRejected("Напишите вопрос о статистике или используйте /stop_auto.")
            else:
                from services.ai.agent import AgentService
                AgentService(self.core).queue(self.workspace, binding.user_id, text, command_id,
                    conversation="telegram:"+self.scope, channel="telegram", chat_id=chat["id"])
                response = "Сообщение принято. Агент проверит данные; рекламные действия потребуют CONFIRM."
            status = "succeeded"
        except ActionRejected as error:
            response, status = str(error), "denied"
        with self.core.sessions.begin() as session:
            command = session.get(TelegramCommand, command_id)
            command.status = status
            command.payload = {**command.payload, "response": response}
        return response

    async def notify_agent_next(self):
        with self.core.sessions.begin() as session:
            message = session.scalar(select(AgentMessage).join(User, AgentMessage.actor_id == User.id).where(
                AgentMessage.workspace_id == self.workspace, User.workspace_id == self.workspace,
                User.role.in_(("admin", "operator")), AgentMessage.actor_id.in_([b.user_id for b in self.bindings]),
                AgentMessage.status.in_(("completed", "failed", "expired", "cancelled")),
                AgentMessage.telegram_status.is_(None)).order_by(AgentMessage.created_at).with_for_update(skip_locked=True).limit(1))
            if not message:
                return None
            # Web turns are not dispatched to Telegram.
            if message.payload.get("channel") != "telegram":
                message.telegram_status = "not_applicable"
                return message.id
            binding = next(b for b in self.bindings if b.user_id == message.actor_id)
            if message.payload.get("chat_id") != binding.chat_id:
                message.telegram_status = "invalid_binding"
                return message.id
            claimed = session.execute(update(AgentMessage).where(AgentMessage.id == message.id,
                AgentMessage.telegram_status.is_(None)).values(telegram_status="attempting"))
            if claimed.rowcount != 1: return None
            identity = message.id
            from services.ai.agent import AgentService
            view = AgentService(self.core).view(session, message)
        text = view["answer"] or f"Анализ: {view['status']}. {view['error_code'] or ''}"
        if view["decision"] and view["decision"]["status"] == "ready":
            text = review_text(view["decision"])
        try:
            await self.api.call("sendMessage", {"chat_id": binding.chat_id, "text": text[:4000]})
            status = "sent"
        except TelegramFailure:
            status = "unknown"
        with self.core.sessions.begin() as session:
            session.get(AgentMessage, identity).telegram_status = status
        return identity

    def handle(self, update):
        callback = update.get("callback_query", {})
        sender = callback.get("from", {}).get("id")
        message = callback.get("message", {})
        chat = message.get("chat", {})
        binding = next((b for b in self.bindings if b.telegram_user_id == sender and b.chat_id == chat.get("id")), None)
        if not binding or chat.get("type") != "private":
            raise ActionRejected("Telegram user is not authorized")
        pieces = callback.get("data", "").split(":")
        if len(pieces) != 2 or pieces[0] not in ("approve", "review", "reject") or len(pieces[1]) != 32:
            raise ActionRejected("Invalid callback")
        operation, token = pieces
        command_id = str(uuid5(NAMESPACE_URL, f"telegram:{self.scope}:{update['update_id']}"))
        with self.core.sessions.begin() as session:
            from services.ai.engine import authorize
            authorize(session, self.workspace, binding.user_id)
            decision = session.scalar(select(AIDecision).where(AIDecision.workspace_id == self.workspace,
                AIDecision.payload["callback_token"].as_string() == token))
            if not decision or decision.owner_id != binding.user_id or decision.payload.get("telegram") != {
                "chat_id": binding.chat_id, "message_id": message.get("message_id")}:
                raise ActionRejected("Callback does not match its message")
            if operation == "approve" and len(review_text(self.core.view(session, decision), reasons=False, truncate=False)) > 3500:
                raise ActionRejected("Review and confirm this large plan in the web interface")
            existing = session.get(TelegramCommand, command_id)
            if existing and (existing.payload["decision_id"], existing.payload["operation"], existing.payload["actor_id"]) != (decision.id, operation, binding.user_id):
                raise ActionRejected("Telegram update was already used")
            if existing and existing.status != "processing":
                return existing.payload["response"]
            if not existing:
                session.add(TelegramCommand(id=command_id, workspace_id=self.workspace, status="processing", created_at=self.core.clock(),
                    payload={"decision_id": decision.id, "operation": operation, "actor_id": binding.user_id}))
            identity = decision.id
        # Durable proposal resolution makes even recovery of 'processing' safe.
        try:
            if operation == "review":
                with self.core.sessions() as session:
                    response = review_text(self.core.view(session, session.get(AIDecision, identity)))
            else:
                view = self.core.resolve(self.workspace, binding.user_id, identity, operation, channel="telegram")
                response = review_text(view)
            status = "succeeded"
        except ActionRejected as error:
            response, status = str(error), "denied"
        with self.core.sessions.begin() as session:
            command = session.get(TelegramCommand, command_id)
            command.status = status
            command.payload = {**command.payload, "response": response}
        return response

    async def poll_once(self):
        with self.core.sessions.begin() as session:
            session.execute(insert_for(session, TelegramCursor.__table__).values(workspace_id=self.scope,
                next_update=0).on_conflict_do_nothing(index_elements=["workspace_id"]))
            offset = session.get(TelegramCursor, self.scope).next_update
        updates = await self.api.call("getUpdates", {"offset": offset, "limit": 100, "timeout": 20, "allowed_updates": ["callback_query", "message"]})
        for item in sorted(updates, key=lambda u: u["update_id"]):
            callback = item.get("callback_query")
            if callback:
                try:
                    response = self.handle(item)
                except ActionRejected as error:
                    response = str(error)
            elif item.get("message"):
                try:
                    response = self.handle_message(item)
                except ActionRejected:
                    response = None  # Unauthorized chats receive no private data.
            with self.core.sessions.begin() as session:
                session.execute(update(TelegramCursor).where(TelegramCursor.workspace_id == self.scope,
                    TelegramCursor.next_update <= item["update_id"]).values(next_update=item["update_id"]+1))
            # Approval/replay result and cursor are durable before optional UI
            # acknowledgements; an expired callback cannot poison the inbox.
            if callback:
                try:
                    if callback.get("data", "").startswith("review:") and response.startswith("AI:"):
                        message = callback["message"]
                        await self.api.call("editMessageText", {"chat_id": message["chat"]["id"],
                            "message_id": message["message_id"], "text": response,
                            "reply_markup": message.get("reply_markup", {"inline_keyboard": []})})
                    await self.api.call("answerCallbackQuery", {"callback_query_id": callback["id"],
                        "text": "Состояние доступно в сообщении" if callback.get("data", "").startswith("review:") and response.startswith("AI:") else response[:190], "show_alert": True})
                except TelegramFailure:
                    pass
            elif item.get("message") and response:
                # Cursor is committed before the acknowledgement. Its uncertain
                # delivery cannot cause this message to enqueue another plan.
                try:
                    await self.api.call("sendMessage", {"chat_id": item["message"]["chat"]["id"], "text": response[:4000]})
                except TelegramFailure:
                    pass


async def run():
    if os.environ.get("TELEGRAM_ENABLED", "false").lower() != "true":
        return
    from services.actions.engine import ActionEngine
    from services.actions.settings import policy_from_environment
    from services.ai.engine import CopilotEngine
    from services.storage.database import make_engine, sessions
    token = Path(os.environ["TELEGRAM_BOT_TOKEN_FILE"]).read_text(encoding="utf-8-sig").strip()
    bindings = json.loads(Path(os.environ["TELEGRAM_BINDINGS_FILE"]).read_text(encoding="utf-8-sig"))
    database = make_engine()
    bot = ApprovalBot(CopilotEngine(ActionEngine(sessions(database), policy_from_environment())),
        TelegramAPI(token), os.environ.get("WORKSPACE_ID", "default"), bindings)
    try:
        while True:
            try:
                await bot.notify_next()
                await bot.notify_agent_next()
                await bot.poll_once()
            except (TelegramFailure, ActionRejected):
                await asyncio.sleep(5)
    finally:
        database.dispose()


if __name__ == "__main__":
    asyncio.run(run())
