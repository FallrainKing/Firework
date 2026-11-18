/// <reference types="vite/client" />

declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<{}, {}, any>
  export default component
}

declare module '/vendor/pdfjs/legacy/build/pdf.mjs' {
  export const GlobalWorkerOptions: { workerSrc: string }
  export function getDocument(options: Record<string, unknown>): { promise: Promise<any> }
  export class TextLayer {
    constructor(options: Record<string, unknown>)
    render(): Promise<void>
    cancel(): void
  }
}
