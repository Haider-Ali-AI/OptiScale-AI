# Limitations

- **Synthetic data**: the demo and benchmark data are simulated; ROAS, CPA and model accuracy on them say nothing about real advertisers.
- **Observational, not causal**: model predictions and allocations reflect historical associations; shifting budget may not produce the estimated revenue.
- **Revenue ≠ profit**: campaign revenue is platform-attributed revenue. Profit appears only in the commerce pilot when costs are recorded and gates pass.
- **Spark**: requires a local JDK; it was not runnable in this environment. Local single-machine timings do not represent cluster performance; Spark's JVM start-up dominates small inputs.
- **10M rows**: supported by the backend, not yet measured on this machine.
- **Commerce**: own order/cost CSV import and custom reconciliation have no screen in this release (backend API only). Real merchant validation pending.
- **AI assistant**: optional; not verified against the live NVIDIA endpoint.
- **Security model**: local mode has no authentication (loopback only). Hosted mode is one shared owner password; no multi-user roles.
- **Windows**: 10 backend tests are POSIX/hosted-environment specific and fail on Windows (see 04-test-baseline.md); one test has a stale hardcoded date.
- **Accessibility**: keyboard, labels, contrast tokens and chart tables were implemented and spot-checked; no formal screen-reader audit was done.
- **Brand**: "SignalSpend AI" is a working name; trademark availability not checked.
