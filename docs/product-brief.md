# Contextual creative product brief

5 November 2026 · Working direction for the ElevenLabs application. Application deadline: **16 November 2026, 18:30 GMT**. [Role](https://jobs.ashbyhq.com/elevenlabs/3abf96ca-2937-4290-9d23-5208aece08b2)

## Pitch

**Turn one brief into a YouTube campaign plan. Find videos where the product is relevant, pair each group with an ad and a demo that fit, and use delivery and viewer activity to plan the next test.**

Start with a media buyer running YouTube campaigns for products that benefit from demonstration. They can use the available placements to refine the brief before production. The buyer reviews a proposed package for each context containing a list of videos, an approved creative version, and the destination where viewers can try what the ad showed.

For ElevenLabs, show what Ads Engine could do when the context changes within a single language. ElevenCreative produces and versions the ad; an owned demo can use ElevenAgents to let the viewer choose or ask for the example that matters. The planner can see the connection between the original brief, the creative decision, the viewer task and the next brief. The public Ads Engine integration documents Google Search text and no public Ads Engine API, so the application workflow can stand on its own. [Ads Engine](https://elevenlabs.io/docs/overview/capabilities/ads-engine) · [ElevenCreative Flows](https://elevenlabs.io/docs/eleven-creative/products/flows) · [ElevenAgents client tools](https://elevenlabs.io/docs/eleven-agents/customization/tools/client-tools)

For a standalone product, test whether agencies need to carry approved claims, asset rights, creative decisions and experiment evidence across the tools they already use. Google already offers multimodal creative in Asset Studio and is testing conversations from YouTube ads. Meta is investing in generation and ad ranking. Runway already connects ad accounts and uses campaign performance to improve creative. Portability and the handoff into a measurable product experience are hypotheses to validate with practitioners. A useful early signal is that a planner brings a second brief and names a handoff they would replace. [Google Demand Gen](https://blog.google/products/ads-commerce/demand-gen-drop-august-2026/) · [Meta ads](https://about.fb.com/news/2026/01/2026-ai-drives-performance/) · [Runway Ads](https://help.runwayml.com/hc/en-us/articles/56690810792339-Introduction-to-Runway-Ads)

## Candidate brief from ElevenLabs ads

On 5 November 2026, Google's public index for the verified Eleven Labs Inc. advertiser returned ads with the YouTube filter selected. One video entry, shown that day, promotes realistic AI voices and shows five variations. Understory's ElevenLabs snapshot covers Google Search and Display, Meta, LinkedIn and X. Use it to study positioning, and use Google's YouTube filter for YouTube references. Run duration, repeated use and Understory's creative scores provide context for selecting examples. Campaign outcomes would require separate evidence. [Understory snapshot](https://www.understoryagency.com/b2b-ad-libraries/elevenlabs) · [YouTube advertiser listing](https://adstransparency.google.com/advertiser/AR03192903667376193537?region=anywhere&platform=YOUTUBE) · [Video reference](https://adstransparency.google.com/advertiser/AR03192903667376193537/creative/CR16874364870290571265?region=anywhere)

A candidate for the application is to use that broad voice promise as a reference for two original Text to Speech ads. Each ad gives a short preview and invites the viewer to compare two takes on our demo page. The campaign handoff maps each ad to its intended placements and to a link that opens the matching example. [ElevenLabs Text to Speech](https://elevenlabs.io/text-to-speech)

| Ad context | What the viewer does after clicking |
| --- | --- |
| Video editing tutorials | Watch the same short clip with Take A, then switch to Take B. The footage and words stay the same while the delivery changes. Pick the take that fits the timing and replay the clip with that narration. |
| Audiobook production tutorials | Read a short passage and listen to two deliveries of those same words. Pick the take that fits the scene and replay the selected reading. |

Build one comparison page with two versions of its content. Prepare the clips and audio in advance. The ad link selects the example, and the page gives the viewer controls to play either take and choose one. Record arrivals, playback and selections by ad version. Count a completed comparison when the viewer finishes both short samples and chooses a take. The hypothesis is that matching the proof and the demo task to the viewing context will increase completed comparisons.

Link to the public ads as research references. Build the cuts with original scripts and footage and owned or appropriately licensed audio. Use published brand assets within the applicable brand guidelines and obtain permission if the intended use requires it. ElevenLabs documents non-commercial use with attribution for free-plan output. [Brand guidelines](https://elevenlabs.io/brand) · [Usage terms](https://elevenlabs.io/docs/overview/administration/billing)

## User journey

The POC uses the two Text to Speech contexts above. The earlier recorder storyboard illustrates the workflow. For the playable build, use original or permitted media.

| Moment | User action and visible result |
| --- | --- |
| Brief | The planner sets the product, goal, approved claims, source assets and two viewing contexts. Each context has a source and a short reason the product could be relevant. |
| Find placements | The tool searches for videos in each context. Given an independently supplied catalog, it can propose assignments to either creative and queue ambiguous items. The buyer reviews the lists, checks for overlap and exports the approved placements. |
| Compare | The planner switches between two cuts of the same Text to Speech offer. One shows how voice delivery fits a video edit. The other shows how delivery changes the feel of a passage. The screen shows the opening, proof and call to action for each cut. |
| Set up the campaign | Our tool proposes which cut should run in each context and where it should send viewers. The media buyer approves the objective, format, placement groups, budget and dates. They upload the cuts to YouTube, attach the videos and destination links to ads in Google Ads, and launch the campaign there. |
| Monitor delivery | Google decides when to serve eligible ads. Our tool keeps the approved plan alongside the settings the buyer actually used, any known changes and the delivery Google reports. The buyer can see whether the campaign is serving and whether reported placements match the plan. |
| Try the product | The viewer lands on the example the ad promised, plays both takes and chooses one. |
| Review and revise | The planner reviews delivery and viewer activity together. If a cut received little exposure, check the placement list and delivery settings first. If viewers reach the demo but seldom complete the comparison, inspect where they stop and test a change to the example or the ad's promise. |

The build should preserve the viewer's choice even when a destination opens with the wrong context or an example is unavailable. Offer a useful default and let the viewer choose again.

## What we capture between production and review

1. **The approved plan and the launch settings.** Keep the cut and its version, intended placements, destination, objective, format, budget and dates. Once configured, record the YouTube video ID, Google Ads campaign, ad group and ad IDs, actual settings and known changes. This lets a planner distinguish a creative change from a delivery change.
2. **Reported delivery.** Use Google Ads reports for impressions, views, clicks, spend and reported placements. Some campaign types support specific YouTube channel or video placements. Format and network settings affect where an ad can appear. Placement reports can group low-volume rows under “Other” and may report at a broader level than the individual ad. Keep that reporting level visible in the review. [Campaign setup](https://support.google.com/google-ads/answer/2375497) · [Placement targeting](https://support.google.com/google-ads/answer/2470108) · [Placement reports](https://developers.google.com/google-ads/api/docs/reporting/placement-views)
3. **Activity after the click.** Give each ad a destination link that identifies its creative version. The owned demo records arrivals, examples opened and tasks completed. The link identifies the ad version associated with the visit. Publisher placement comes from Google's reporting where available.

For the zero-cost build, export a campaign setup for the buyer and rehearse the review using clearly labelled sample delivery reports and actual local demo events. The test account can verify API access. Real campaign delivery and spend require a live campaign.

The local placement review tool searches several phrases per creative using YouTube's official search API and presents candidates in the returned order. The buyer can select videos and export a separate list per creative. For an independently supplied creator catalog, local rules or Jev through OpenRouter propose assignments to the two creatives and queue ambiguous cases. The buyer can approve proposals in bulk. The paid campaign still needs its placement eligibility and inventory checked in Google Ads. [YouTube search API](https://developers.google.com/youtube/data/reference/rest/v3/search/list) · [Placement review instructions](../README.md#placement-review)

Live search returned 327 distinct video candidates for editing and 316 for audiobook production, deduplicated within each context. A live result was exported as a placement URL. Bulk approval was exercised with sample assignments. Jev's request and review logic passed a simulated API test. A live model run and the accuracy of its assignments on a real creator catalog remain to be measured.

## How we will know what worked

- **Operator value.** Measure time to an approved placement list and how many proposed assignments the buyer accepts, rejects or moves to another creative. Compare with their usual workflow if they can share a baseline. Check whether the approved package is ready to enter in Google Ads.
- **Viewer value.** Count a completed comparison when the viewer finishes both samples and chooses a take. Log arrival, playback and selection by ad version. A local run verifies the workflow and instrumentation. Testing viewer impact requires real participants and an appropriate comparison.
- **Context fit.** When enough first-party traffic exists, randomize cuts within a context and show both tailored cuts across both contexts. This distinguishes a strong cut that wins everywhere from a cut that benefits from the match. To test the destination itself, separately assign standard versus guided destinations after arrival. Keep outcomes and denominators for each comparison explicit.
- **Paid delivery.** A later authorized pilot must verify that the chosen Video campaign can target the intended placements, that the resulting inventory is sufficient, and that the reports can answer the planned comparison. The test account verified reads and returned empty reports. Paid lift and per-publisher creative outcomes remain open. [Placement targeting](https://support.google.com/google-ads/answer/2470108) · [Placement reports](https://developers.google.com/google-ads/api/docs/reporting/placement-views) · [Video experiments](https://support.google.com/google-ads/answer/10436762)

## Architecture

The proposed modular monolith keeps campaign records in the product and lets a selectable agent runtime act through scoped tools. The build plan covers the application milestones, DeepSeek experiment and provider checks. [Architecture](architecture-plan.md) · [Build plan](build-plan.md)
