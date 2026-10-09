import RuleRecommendations from "../../components/RuleRecommendations";
import SessionBar from "../../components/SessionBar";
export default function RecommendationsPage() {
  return (
    <main className="dashboard rules-surface">
      <header className="topbar">
        <a className="brand" href="/">
          ACC<span>Advertising Control Center</span>
        </a>
        <SessionBar />
      </header>
      <section className="heading">
        <div>
          <p className="eyebrow">АНАЛИЗ БЕЗ AI</p>
          <h1>Центр рекомендаций</h1>
          <p className="subtitle">
            Приоритеты проверки и причины по сохранённым симуляциям
          </p>
        </div>
      </section>
      <RuleRecommendations />
    </main>
  );
}
