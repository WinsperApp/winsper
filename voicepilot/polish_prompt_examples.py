from __future__ import annotations

from typing import Literal


PromptProfile = Literal["fast", "balanced", "best"]


def fast_selected_examples(instruction: str, *, compact: bool = False) -> str:
    folded = " ".join(instruction.casefold().split())
    shortening = any(word in folded for word in ("short", "concise", "summar"))
    currency = any(word in folded for word in ("amount", "currency", "currencies"))
    if "exactly" in folded and "word" in folded:
        if compact:
            return """EXAMPLE (pattern only; never copy its content):
USER_REQUEST: Answer the selected question in exactly eight words.
SELECTED_TEXT: Why should travelers verify passport details before booking?
RESULT: Travelers verify passport details to prevent booking errors."""
        return """EXAMPLES (patterns only; never copy their content):
USER_REQUEST: Explain this in exactly eight words.
SELECTED_TEXT: Why should teams test backups before migrating systems?
RESULT: Teams test backups early to confirm reliable recovery.

USER_REQUEST: Answer the selected question in exactly eight words.
SELECTED_TEXT: Why should travelers verify passport details before booking?
RESULT: Travelers verify passport details to prevent booking errors.

USER_REQUEST: Answer the selected question in exactly five words.
SELECTED_TEXT: Why do backups matter to customers?
RESULT: Reliable backups protect customer data."""
    if "exactly" in folded and "sentence" in folded:
        return """EXAMPLE (pattern only; never copy its content):
USER_REQUEST: Write exactly two short sentences explaining this role.
SELECTED_TEXT: data engineer
RESULT: A data engineer builds pipelines. They maintain reliable data systems."""
    if "synonym" in folded:
        return """EXAMPLE (pattern only; never copy its content):
USER_REQUEST: Replace this with one precise synonym.
SELECTED_TEXT: quick
RESULT: rapid"""
    if "translat" in folded:
        return """EXAMPLE (pattern only; never copy its content):
USER_REQUEST: Translate this to Spanish.
SELECTED_TEXT: The review is on Wednesday.
RESULT: La revisión es el miércoles."""
    if "title case" in folded:
        return """EXAMPLE (pattern only; never copy its content):
USER_REQUEST: Convert this to title case.
SELECTED_TEXT: release readiness notes
RESULT: Release Readiness Notes"""
    if "remove" in folded or "delete" in folded:
        return """EXAMPLE (pattern only; never copy its content):
USER_REQUEST: Remove only the greeting.
SELECTED_TEXT: Hello Mina, the Q3 plan is ready today.
RESULT: The Q3 plan is ready today."""
    if "try" in folded and "except" in folded:
        return """EXAMPLE (pattern only; never copy its content):
USER_REQUEST: Wrap this in a try except block handling request exceptions.
SELECTED_TEXT: response = client.get(url)
print(response.json())
RESULT: try:
    response = client.get(url)
    print(response.json())
except RequestException as error:
    print(error)"""
    if "without translating" in folded:
        return """EXAMPLE (pattern only; never copy its content):
USER_REQUEST: Make this professional without translating it.
SELECTED_TEXT: कृपया SDK review आज finish करो।
RESULT: कृपया SDK review आज finish करें।"""
    if "summar" in folded:
        return """EXAMPLE (pattern only; never copy its content):
USER_REQUEST: Summarize this in one short sentence without losing the people or technologies.
SELECTED_TEXT: Morgan reviewed Django logs for Atlas, found an SSO issue, and asked Lee to update R3 documentation.
RESULT: Morgan found an SSO issue in Atlas's Django logs and asked Lee to update R3 documentation."""
    if shortening and currency:
        return """EXAMPLE (pattern only; never copy its content):
USER_REQUEST: Make this at least half shorter while preserving both amounts, currencies, audience, and timing.
SELECTED_TEXT: Please send a detailed comparison of CHF 7,400 and NZD 9,200 proposals to finance before Friday afternoon.
RESULT: Finance: compare CHF 7,400 and NZD 9,200 Friday."""
    if currency:
        return """EXAMPLE (pattern only; never copy its content):
USER_REQUEST: Make this friendlier without changing any amount or currency.
SELECTED_TEXT: The Paris quote is EUR 740 and Tokyo quote is JPY 920.
RESULT: Paris's quote is EUR 740, and Tokyo's is JPY 920."""
    if "casual" in folded:
        return """EXAMPLE (pattern only; never copy its content):
USER_REQUEST: Do not make this formal or professional; keep it casual in no more than nine words.
SELECTED_TEXT: The launch note is technically complete and ready to share with the group.
RESULT: Launch note's done and ready to share."""
    if any(word in folded for word in ("professional", "formal", "friendly", "tone")):
        return """EXAMPLE (pattern only; never copy its content):
USER_REQUEST: Make this professional and concise.
SELECTED_TEXT: hey the Q3 plan is late please send it tomorrow
RESULT: The Q3 plan is late. Please send it tomorrow."""
    if shortening:
        if "without losing" in folded:
            return """EXAMPLE (pattern only; never copy its content):
USER_REQUEST: Make this substantially shorter without losing Thursday, Lisbon, R4, or the delay.
SELECTED_TEXT: The team met on Thursday in Lisbon to discuss the delayed R4 migration plan in detail.
RESULT: Thursday's Lisbon meeting covered the delayed R4 migration."""
        if "quarter" in folded or "third" in folded or "half" in folded:
            return """EXAMPLE (pattern only; never copy its content):
USER_REQUEST: Make this at least half shorter while preserving the audience and deadline.
SELECTED_TEXT: Please send the detailed deployment update to the finance team before Friday afternoon.
RESULT: Send finance deployment update by Friday."""
        return """EXAMPLE (pattern only; never copy its content):
USER_REQUEST: Make this concise without changing the status or reason.
SELECTED_TEXT: Release delta is delayed because the TLS compatibility review is still running.
RESULT: Release delta is delayed pending the TLS compatibility review."""
    if "answer" in folded or "explain" in folded:
        return """EXAMPLE (pattern only; never copy its content):
USER_REQUEST: Answer this in one concise sentence.
SELECTED_TEXT: What is a cache?
RESULT: A cache stores reusable data for faster access."""
    return ""


def full_selected_examples(prompt_profile: PromptProfile) -> str:
    count_example = """EXAMPLES (patterns only; never copy their content):
USER_REQUEST: Answer the selected question in exactly six words.
SELECTED_TEXT: Why do backups matter during system migrations?
RESULT: Backups protect data during risky migrations.

USER_REQUEST: Make this at least one third shorter; preserve both amounts and the deadline.
SELECTED_TEXT: Please send a detailed comparison of USD 2,400 and EUR 2,100 to finance before Tuesday.
RESULT: Compare USD 2,400 and EUR 2,100 for finance before Tuesday."""
    if prompt_profile == "best":
        return """EXAMPLES (patterns only; never copy their content):
USER_REQUEST: Answer in exactly seven words.
SELECTED_TEXT: Why should teams test their backups?
RESULT: Teams test backups to verify reliable recovery.

USER_REQUEST: Answer in exactly twelve words.
SELECTED_TEXT: Why should teams rotate credentials?
RESULT: Teams rotate credentials regularly to limit exposure from compromised old access secrets.

USER_REQUEST: Do not make this formal; keep it casual in no more than eight words.
SELECTED_TEXT: The security review is technically complete and ready to circulate.
RESULT: Security review's done and ready to share.

USER_REQUEST: Make this at least half shorter; preserve Helios and 03 June 2028.
SELECTED_TEXT: Please send everyone a detailed written progress update about project Helios before the meeting on 03 June 2028.
RESULT: Send a Helios update before 03 June 2028.

USER_REQUEST: Summarize in exactly two sentences. Preserve project, status, reason, owner, budget, checkpoint, and uncertainty.
SELECTED_TEXT: Project Nova is blocked because audit A-9 is open. Mei owns the audit. The budget is GBP 12,400. The checkpoint is 4 May 2028 at 10:00 UTC. No launch date is committed.
RESULT: Project Nova is blocked by open audit A-9, owned by Mei, with a GBP 12,400 budget. The checkpoint is 4 May 2028 at 10:00 UTC, and no launch date is committed.

USER_REQUEST: Explain in one sentence. Preserve the exact literals 4 and ERR-8.
SELECTED_TEXT: if attempts >= 4: stop("ERR-8")
RESULT: The process stops with ERR-8 when attempts reach 4.

USER_REQUEST: Make this friendlier without changing the quotation, person, issue, or time.
SELECTED_TEXT: Lee wrote, "mode=safe" in issue K-4 at 08:10 UTC.
RESULT: Lee shared, "mode=safe" in issue K-4 at 08:10 UTC.

USER_REQUEST: Change only retries to 4. Preserve the complete YAML and return YAML only.
SELECTED_TEXT: service: nova
region: west
retries: 2
enabled: true
RESULT: service: nova
region: west
retries: 4
enabled: true"""
    return f"""{count_example}

USER_REQUEST: Replace it with one precise synonym.
SELECTED_TEXT: quick
RESULT: rapid

USER_REQUEST: Remove the greeting.
SELECTED_TEXT: Hello Mina, the report is ready.
RESULT: The report is ready.

USER_REQUEST: Translate this to French.
SELECTED_TEXT: The review is on Wednesday.
RESULT: La revue est mercredi.

USER_REQUEST: Make this much shorter.
SELECTED_TEXT: The team met yesterday to discuss the delayed release plan in detail.
RESULT: The team discussed the delayed release plan.

USER_REQUEST: Answer in exactly eight words.
SELECTED_TEXT: Why should travelers check passport details before booking flights?
RESULT: Travelers check passport details before booking international flights.

USER_REQUEST: Add one clear comment without changing the code.
SELECTED_TEXT: def total(values):
    return sum(values)
RESULT: # Return the sum of all values.
def total(values):
    return sum(values)

USER_REQUEST: Make concise without changing the status or reason.
SELECTED_TEXT: Service beta is blocked because the TLS reliability review is running.
RESULT: Service beta is blocked pending the TLS reliability review.

USER_REQUEST: Make this professional without translating it.
SELECTED_TEXT: कृपया SDK review आज finish करो।
RESULT: कृपया SDK review आज finish करें।"""


def full_polish_examples(prompt_profile: PromptProfile, operation: str) -> str:
    if operation != "preserve":
        return ""
    if prompt_profile == "best":
        return """EXAMPLES (patterns only; never copy their content):
RAW: The review is approved. On second thought, keep it pending.
RESULT: Keep the review pending.

RAW: My bicycle is outside. Not my bicycle, my scooter is outside.
RESULT: My scooter is outside.

RAW: Tell her the draft is careless. No, don't say that. Say the draft needs more review.
RESULT: Tell her the draft needs more review.

RAW: The estimate is around 12 million, not 20 million.
RESULT: The estimate is around 12 million, not 20 million.

RAW: I first reported 08:15 UTC. That came from the refresh. The actual alert was 08:22 UTC.
RESULT: The actual alert was at 08:22 UTC.

RAW: रिपोर्ट बुधवार को है, नहीं, गुरुवार को है।
RESULT: रिपोर्ट गुरुवार को है।

RAW: um please uh send the API update on Tuesday
RESULT: Please send the API update on Tuesday.

RAW: create a list first item review contract make contract bold second item call vendor
RESULT: - Review **contract**
- Call vendor"""
    correction_examples = """EXAMPLES (patterns only; never copy their content):
RAW: I booked Monday, no, sorry, Tuesday.
RESULT: I booked Tuesday.

RAW: We meet weekly, um, no, not weekly, monthly.
RESULT: We meet monthly.

RAW: The estimate is around 12 million, not 20 million.
RESULT: The estimate is around 12 million, not 20 million.

RAW: um please uh send the API update on Tuesday
RESULT: Please send the API update on Tuesday.

RAW: Create a CSV with active as the column and yes as its value.
RESULT: Create a CSV with active as the column and yes as its value.

RAW: create a task list first item review the draft make sure draft is bold second item publish the update
RESULT: - Review the **draft**
- Publish the update

RAW: रिपोर्ट बुधवार को है, नहीं, गुरुवार को है।
RESULT: रिपोर्ट गुरुवार को है।"""
    return f"""{correction_examples}

RAW: कृपया SDK status आज check करो
RESULT: कृपया SDK status आज check करो।"""
