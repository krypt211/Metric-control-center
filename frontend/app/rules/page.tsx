import SmartRules from "../../components/SmartRules";
import SessionBar from "../../components/SessionBar";
export default function RulesPage() {
  return (
    <main className="dashboard rules-surface">
      <SessionBar />
      <section className="heading">
        <div>
          <p className="eyebrow">БЕЗОПАСНАЯ СИМУЛЯЦИЯ</p>
          <h1>Правила рекламы</h1>
          <p className="subtitle">
            Конструктор условий и проверка объявлений · только DRY RUN
          </p>
        </div>
      </section>
      <SmartRules />
    </main>
  );
}
