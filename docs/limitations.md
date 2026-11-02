# Limitations

- **Synthetic data**: the demo and benchmark data are simulated; ROAS, CPA and model accuracy on them say nothing about real advertisers.
- **Observational, not causal**: model predictions and allocations reflect historical associations; shifting budget may not produce the estimated revenue.
- **Revenue ≠ profit**: campaign revenue is platform-attributed revenue. Profit appears only in the commerce pilot when costs are recorded and gates pass.
- **Spark**: requires a local Java 17/21/25 runtime (verified with Temurin JRE 17.0.20.1). Local single-machine timings do not represent cluster performance; Spark's ~10 s JVM start-up dominates small inputs.
- **Benchmark variance**: this laptop had ~4 GB RAM free; repeats vary (e.g. Pandas 10M median 4.3 s in one run, 7.5 s in another). Compare engines within the same job.
- **Commerce**: own order/cost CSV import and comparisons are available in the UI and were tested with fictional fixtures only. Real merchant validation is pending.
- **AI assistant**: optional; not verified against the live NVIDIA endpoint.
- **Security model**: local mode has no authentication (loopback only). Hosted mode is one shared owner password; no multi-user roles.
- **Windows**: 9 backend tests are POSIX/hosted-environment specific and fail on Windows (see 04-test-baseline.md). The stale-date test was fixed (T-1).
- **Accessibility**: keyboard, labels, contrast tokens and chart tables were implemented and spot-checked; no formal screen-reader audit was done.
- **Brand**: "SignalSpend AI" is a working name; trademark availability not checked.
