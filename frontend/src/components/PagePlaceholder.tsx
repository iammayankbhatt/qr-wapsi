export default function PagePlaceholder({ title, detail }: { title: string; detail?: string }) {
  return (
    <section className="rounded-lg bg-white p-8 shadow-sm">
      <h1 className="text-4xl font-bold">{title}</h1>
      {detail && <p className="mt-2 text-navy/70">{detail}</p>}
      <p className="mt-4 text-navy/60">Placeholder — coming in a later step.</p>
    </section>
  )
}
