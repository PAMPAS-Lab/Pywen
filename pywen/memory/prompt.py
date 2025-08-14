compression_prompt = """
Your task is to create a detailed summary of the conversation so far, paying close attention to the user's explicit requests and your previous actions.
This summary should be thorough in capturing technical details, code patterns, and architectural decisions that would be essential for continuing development work without losing context.

Before providing your final summary, wrap your analysis in <analysis> tags to organize your thoughts and ensure you've covered all necessary points.

Your summary should include the following sections:

1. Primary Request and Intent: Capture all of the user's explicit requests and intents in detail
2. Key Technical Concepts: List all important technical concepts, technologies, and frameworks discussed.
3. Files and Code Sections: Enumerate specific files and code sections examined, modified, or created. Pay special attention to the most recent messages and include full code snippets where applicable.
4. Errors and fixes: List all errors that you ran into, and how you fixed them. Pay special attention to specific user feedback.
5. Problem Solving: Document problems solved and any ongoing troubleshooting efforts.
6. All user messages: List ALL user messages that are not tool results. These are critical for understanding the users' feedback and changing intent.
7. Pending Tasks: Outline any pending tasks that you have explicitly been asked to work on.
8. Current Work: Describe in detail precisely what was being worked on immediately before this summary request.

The conversation history is as follows: \n {}
"""


keyword_continuity_score_prompt = """
You are Pywen’s memory-compression grader.

Definitions:
- keyword_score: 1.00 if every piece of information that could change the agent’s next action is recoverable; 0.00 if none.
- continuity_score: 1.00 if logical flow (problem → solution → result) is perfectly preserved; 0.00 if disjointed.

Return exactly one line starting with "Result: " followed by two fixed-point numbers, space-separated, rounded to two decimals.
Example: Result: 0.92 0.88

<summary>\n{}\n</summary>

<original>\n{}\n</original>
"""