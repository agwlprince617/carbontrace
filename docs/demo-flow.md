# CarbonTrace demo

[Public Cloud Run demo](https://carbontrace-demo-683634661093.us-central1.run.app).
The public app supports planning, recorded evidence and sponsor-funded Gemini runs.

1. Open **Before you send**. Keep Clamp selected and choose the `chat.light`
   benchmark. Explain the saved quality evidence, assumed output size and cost
   range. CLEER supplies environmental context, not this prompt's actual footprint.
2. Use the suggested model. Editing the prompt removes the exact quality match;
   the app then asks for a manual choice instead of promising equivalent quality.
3. Review the sponsor reservation, then use **Compare Flash-Lite + Flash** to send
   the same prompt/code to both models. Inspect both outputs, real usage, catalog
   cost and response times. **Run Gemini** still sends only the selected model.
   Fresh quality is not automatically checked. Preview and preparation make no
   model calls. During rehearsal, reopen the
   [saved shipping-fee pair](https://carbontrace-demo-683634661093.us-central1.run.app/?hosted=592fc8d97aca4ea5a96ac2cd94c144f6)
   instead of starting another paid run. Saved receipts have seven-day retention.
4. Open **Run & validate** to inspect the bundled recorded comparison. It shows actual responses,
   tokens, catalog cost and correct-function / four-fault checks. Its label makes
   clear that viewing it makes no new calls. Expand the returned tests if useful.
5. Open **Environmental evidence** only to explain the source or calculation.
   Source, licence and uncertainty details stay available in disclosures.
   The hypothetical hardware calculator is excluded from the demo interface.

The shared model allowance is USD 4, including prior usage. USD 3.753830 remained
after paired verification on 18 October 2026. The overall demo allowance is
USD 5 including USD 1 for the update and light hosting, before tax/FX, not a hard
Google billing cap. Live runs expire 6 November 2026 at 11:59 PM IST, or earlier
if the remaining allowance cannot fund the selected request.
The planner and recorded comparison continue to work afterward.

For the separate local workflow, from the project root with the virtual environment
active, run:

```sh
python -m carbontrace.live_compare_cli --id <run-id>
```

Use `--directory <configured-store>` if the server uses a custom store. Read the
exact plan and price, then approve its full hash in that terminal. Quoting does
not authorize execution. The recorded demo is read-only and cannot be replayed.

The packaged snapshot retains the original quote and results unchanged; only its
outer view removes local approval and slot fields. It contains reviewed toy code,
no credentials or personal filesystem paths. It remains separate from fresh output.

![Simplified demo workspace](demo-cleanup-preview.jpg)
