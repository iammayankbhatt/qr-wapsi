import type { ReactNode } from 'react'

/** A phone-sized device frame for the shopkeeper and field-employee screens. */
export default function PhoneFrame({ header, children, footer }: { header: ReactNode; children: ReactNode; footer?: ReactNode }) {
  // 640 px screen: the whole page fits a 1440x900 projector without scrolling
  return (
    <div className="mx-auto w-[430px] shrink-0 rounded-[3rem] bg-navy p-3 shadow-[0_24px_60px_rgba(14,27,61,0.35)]">
      <div className="flex h-[640px] flex-col overflow-hidden rounded-[2.4rem] bg-[#EFE7DD]">
        <div className="flex h-5 items-center justify-center bg-black/90">
          <span className="h-1.5 w-20 rounded-full bg-white/25" />
        </div>
        {header}
        <div className="flex-1 overflow-y-auto">{children}</div>
        {footer}
      </div>
    </div>
  )
}
