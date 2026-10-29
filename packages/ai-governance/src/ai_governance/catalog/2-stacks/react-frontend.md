# React & Modern Frontend Standards

## Invariants
- **Functional Components**: Use functional components with TypeScript and strict props interfaces; no `any` props.
- **Form Validation**: Validate forms with a shared schema (e.g. Zod + `react-hook-form` resolver) and native input types (`type="email"`, `type="url"`); never ad-hoc regex per field.
- **Core Web Vitals & Lazy Loading**: Use `React.lazy` and `Suspense` on large components and routes to optimize LCP, INP, and CLS.
- **Accessibility (A11y)**: Use semantic HTML (`<button>`, `<main>`, `<nav>`), required ARIA attributes, keyboard navigation support, and WCAG AA contrast.
- **Predictable State**: Keep state as local as possible. In SPAs without server routing, synchronize with `window.location.hash`.
