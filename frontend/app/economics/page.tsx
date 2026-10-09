import Economics from "@/components/Economics";
import SessionBar from "@/components/SessionBar";
export default function EconomicsPage() {
  return (
    <main>
      <header className="topbar">
        <a className="brand" href="/">
          ACC<span>Advertising Control Center</span>
        </a>
        <SessionBar />
      </header>
      <section className="heading">
        <div>
          <p className="eyebrow">ФИНАНСОВЫЙ КОНТРОЛЬ</p>
          <h1>Экономика рекламы</h1>
          <p className="subtitle">Профили, апрув и оценка результатов</p>
        </div>
      </section>
      <Economics />
    </main>
  );
}
