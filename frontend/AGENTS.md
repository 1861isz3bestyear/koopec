# Frontend test requirements

- Maintain strictly greater than 95% coverage for statements, branches, functions, and lines across all production TypeScript in `src`. Run `corepack pnpm coverage` before completing changes.
- Exercise every cyclomatic decision outcome with meaningful tests, including success and failure paths, boundaries, and state transitions. Coverage alone does not prove this requirement; review decision outcomes and report any unverified paths.
- Run `corepack pnpm build` and `corepack pnpm test` before completing changes. Do not exclude production code or suppress failures to meet coverage.
- Check text foreground/background contrast at a minimum WCAG AA ratio of 4.5:1 and include a regression that rejects low contrast. Report any visual elements, such as canvas-rendered text, that the automated check does not cover.
- Use ESLint with the strictest compatible TypeScript rules, including type-aware checks. Run `corepack pnpm lint`; warnings must fail the check. Document justified rule conflicts instead of suppressing diagnostics merely to pass.
- Maintain meaningful module and integration tests in the frontend.
- Run end-to-end tests in CI using Playwright and real Chromium against the frontend and backend.
- Merging into the default branch is strictly prohibited until all required CI checks succeed. Configure repository branch protection to enforce this.
