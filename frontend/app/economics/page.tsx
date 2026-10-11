import Economics from "@/components/Economics";
import SessionBar from "@/components/SessionBar";
export default function EconomicsPage() {
  return (
    <main>
      <SessionBar />
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
