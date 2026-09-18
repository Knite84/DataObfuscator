Can you help me draft an implementation plan for building a local-only, data obfuscation tool where the user can copy paste in rich text and the solution will then search for all pronouns and replace them, while using the same replacement pronoun for every instance the original pronoun is used? For example, if John Smith appears in the copy and pasted text 20 times, I want John Smith replaced with the same new pronoun each of the 20 times. I want your opinion on doing this in two passes, a first pass done entirely with traditional methods of scripting and parsing, followed by a semantic pass done by leveraging a small local ai model (served by LM Studio or Unsloth Studio) to ensure any potential protected data (IP or otherwise), is caught too and then addressed.
I want there to be some sort of a review process, like a score sheet for low confidence items that need human in the loop approval, before the system then presents and allows the final, obfuscated version to be viewed and downloaded (or copy/pasted). If this requires a local web server, then I want it containerized in Docker. Single tenet, no need for authentication. No need for data persistence. UI can be very plan off whites and dark greys, simple free fonts, no licensing costs of any kind anywhere in the project. Let me know what questions you have.


My opinion on the two-pass approach: it's the right pattern, with one important rule. Pass 1 (deterministic: regex for emails/phones/IDs, NER via spaCy or similar for names/orgs/places) is cheap, fast, and high-precision. Pass 2 (small local LLM via an OpenAI-compatible endpoint — LM Studio exposes one on localhost:1234, so either LM Studio or any compatible server works) should be used for detection only, never generation: it returns structured JSON (exact quote, category, confidence, reason) and the app maps quotes back to character offsets and applies replacements deterministically. That gives you consistency for free (same source string → same replacement via one mapping table), avoids the model mangling formatting or hallucinating text, and anything the model finds that can't be resolved to an exact span becomes

Questions:
Which tech stack for the app (web server + Pass 1 parsing)?
Python + FastAPI + spaCy (Recommended)
How should the local LLM be served? (LM Studio is a desktop app and can't run inside Docker; note 'Unsloth Studio' is a fine-tuning tool, not a server)
LM Studio on host
You said 'pronouns' but your example is a person's name — I read this as: replace identifying entities consistently. Which categories should Pass 1 + Pass 2 target? (multiple)
People names, Contact/PII patterns, Orgs & places, Biz-sensitive free text
What style of replacement text do you want?
Realistic synthetic names (Recommended)
Input is pasted rich text (HTML). What outputs matter?
Rich HTML in → HTML + TXT out (Recommended)
How should the human-in-the-loop review work for low-confidence findings?
Per-finding approve/edit (Recommended)
What hardware will run the local model? (affects model choice in the plan)
GPU 12GB VRAM; 32GB RAM, 14900 Intel CPU, I'm expecting to use a quant of gemma-4-E4B-it