"""Fantasy baseball AI assistant engine.

Orchestrates the Anthropic API tool-use loop: receives a user question,
calls Claude with tool definitions, executes tool calls against the database,
and returns a data-backed answer.
"""

import json
import logging
from datetime import date, datetime

import anthropic
from sqlalchemy import func, select

from app.config import settings
from app.database import async_session
from app.models.conversation import Conversation, UsageLog
from app.services.assistant_tools import TOOL_DEFINITIONS, TOOL_HANDLERS

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a fantasy baseball analyst embedded in a data-driven analytics \
application. You have access to tools that query a live database of MLB \
statistics, Statcast data, rest-of-season projections, and player rankings.

LEAGUE SCORING CONTEXT:
This is a 10-team H2H Points league (Yahoo, keeper) called "Galactic Empire" \
with these key scoring implications you MUST factor into ALL advice:

1. RELIEVER VALUE: Saves=7, Holds=4, Relief Wins=4. Elite closers and \
setup men are premium assets. A clean closer save inning = 12.5 pts. \
Always consider reliever options when giving roster advice.

2. INNINGS = POINTS: Each out = 1.5 points (IP = 4.5). Innings-eating \
starters with low ERAs are the most valuable pitchers. A 7-IP quality \
start is worth 31.5 points from outs alone.

3. EARNED RUNS ARE DEVASTATING: ER = -4 points. A 5-ER blowup costs \
20 points from ER alone. Always factor in blowup risk when recommending \
streamers. Only recommend streamers projected above 8 points.

4. CONTACT MATTERS: Batter K = -0.5. Over a season, a high-K player \
loses 30-75 points from strikeouts. When comparing similar hitters, \
favor the one with lower K%.

5. WALKS ARE FREE: Batter BB = 1 point. High-OBP players who walk a \
lot get bonus value vs their traditional stat lines.

6. P SLOT FLEXIBILITY: 4 generic P slots can be SP or RP. Recommend \
optimal allocation based on the week's matchups.

7. KEEPER LEAGUE: Factor in long-term value when discussing trades \
and waiver adds. Young players with improving metrics have extra value.

When giving points projections, always show the math so the user \
understands why you're recommending what you're recommending.

RULES:
1. Always use your tools to pull actual data before answering. Never guess \
at statistics or make up numbers. If you're unsure about something, say so.
2. When recommending players, cite specific stats AND projected fantasy \
points to support your advice. Reference both traditional stats and \
Statcast metrics when relevant.
3. When comparing players, use the compare_players tool to get side-by-side \
data. Highlight the most meaningful differences in fantasy points terms.
4. For start/sit decisions, always check today's matchup using \
get_matchup_info and the specific head_to_head data if available. \
Frame advice in terms of projected points for the start.
5. For trade questions, use the evaluate_trade tool to quantify both sides \
using projected fantasy points and surplus value.
6. Be concise and direct. Lead with your recommendation, then support it \
with 2-3 key data points. Don't dump every stat available.
7. If a player search returns multiple matches, ask the user to clarify.
8. When data is limited (small sample size, early in the season), explicitly \
note the uncertainty. Mention the confidence_score from projections.
9. Always frame recommendations in terms of this league's scoring. Say \
"he's projected for 320 ROS points" not just "he has a .380 wOBA."
10. Use plain language. Say "he's hitting the ball harder than almost anyone" \
not "his barrel rate of 15.2% places him in the 94th percentile."
"""

MAX_TOOL_ITERATIONS = 5


def _build_system_prompt(league_context: dict | None = None) -> str:
    prompt = SYSTEM_PROMPT
    if league_context:
        scoring = league_context.get("scoring_type", "unknown")
        size = league_context.get("league_size", 12)
        roster = league_context.get("roster", [])
        depth = "deep" if size <= 10 else ("thin" if size >= 14 else "moderate")

        prompt += f"""
USER'S LEAGUE CONTEXT:
- Scoring format: {scoring}
- League size: {size} teams
- User's current roster: {", ".join(roster) if roster else "not provided"}

Factor this context into all recommendations. In a {size}-team league, \
the waiver wire is {depth}. When suggesting pickups or trades, consider \
what positions the user already has covered and where they have gaps.
"""
    return prompt


class FantasyAssistant:
    def __init__(self) -> None:
        if not settings.anthropic_api_key:
            self.client = None
        else:
            self.client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    def is_configured(self) -> bool:
        return self.client is not None

    async def _check_daily_budget(self) -> bool:
        """Return True if under daily token budget."""
        async with async_session() as session:
            today_start = datetime.combine(date.today(), datetime.min.time())
            result = await session.execute(
                select(
                    func.coalesce(func.sum(UsageLog.input_tokens), 0),
                    func.coalesce(func.sum(UsageLog.output_tokens), 0),
                ).where(UsageLog.created_at >= today_start)
            )
            row = result.one()
            total = row[0] + row[1]
            return total < settings.assistant_daily_token_limit

    async def _load_history(self, session_id: str) -> list[dict]:
        """Load last 10 conversation turns for context."""
        async with async_session() as session:
            result = await session.execute(
                select(Conversation)
                .where(Conversation.session_id == session_id)
                .order_by(Conversation.created_at.desc())
                .limit(20)  # 10 turns = 20 messages (user + assistant)
            )
            rows = list(reversed(result.scalars().all()))

        messages = []
        for row in rows:
            messages.append({"role": row.role, "content": row.content})
        return messages

    async def _save_message(
        self,
        session_id: str,
        role: str,
        content: str,
        tool_calls: str | None = None,
        tool_results: str | None = None,
    ) -> None:
        async with async_session() as session:
            msg = Conversation(
                session_id=session_id,
                role=role,
                content=content,
                tool_calls=tool_calls,
                tool_results=tool_results,
            )
            session.add(msg)
            await session.commit()

    async def _log_usage(self, session_id: str, input_tokens: int, output_tokens: int) -> None:
        async with async_session() as session:
            log = UsageLog(
                session_id=session_id,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                model=settings.assistant_model,
            )
            session.add(log)
            await session.commit()

    async def ask(
        self,
        session_id: str,
        user_message: str,
        league_context: dict | None = None,
    ) -> dict:
        """Main entry point. Returns {answer, session_id, tools_used}."""
        if not self.is_configured():
            return {
                "answer": (
                    "The assistant is not configured. Add your ANTHROPIC_API_KEY to the .env file."
                ),
                "session_id": session_id,
                "tools_used": [],
            }

        # Check daily budget
        if not await self._check_daily_budget():
            return {
                "answer": "Daily token budget reached. Try again tomorrow.",
                "session_id": session_id,
                "tools_used": [],
            }

        # Load conversation history
        history = await self._load_history(session_id)

        # Build messages
        messages = history + [{"role": "user", "content": user_message}]

        system_prompt = _build_system_prompt(league_context)
        tools_used: list[str] = []
        all_tool_calls: list[dict] = []
        all_tool_results: list[dict] = []

        try:
            response = await self.client.messages.create(
                model=settings.assistant_model,
                max_tokens=settings.assistant_max_tokens,
                system=system_prompt,
                tools=TOOL_DEFINITIONS,
                messages=messages,
            )

            # Log token usage
            await self._log_usage(
                session_id,
                response.usage.input_tokens,
                response.usage.output_tokens,
            )

            # Tool-use loop
            iteration = 0
            while response.stop_reason == "tool_use" and iteration < MAX_TOOL_ITERATIONS:
                iteration += 1

                tool_use_blocks = [block for block in response.content if block.type == "tool_use"]

                tool_results = []
                for tool_block in tool_use_blocks:
                    tool_name = tool_block.name
                    tools_used.append(tool_name)
                    all_tool_calls.append(
                        {
                            "name": tool_name,
                            "input": tool_block.input,
                        }
                    )

                    handler = TOOL_HANDLERS.get(tool_name)
                    if handler:
                        try:
                            async with async_session() as db_session:
                                result = await handler(db_session, **tool_block.input)
                        except Exception as e:
                            logger.error(f"Tool {tool_name} failed: {e}")
                            result = {"error": f"Tool execution failed: {e}"}
                    else:
                        result = {"error": f"Unknown tool: {tool_name}"}

                    result_json = json.dumps(result, default=str)
                    all_tool_results.append(
                        {
                            "tool": tool_name,
                            "result": result,
                        }
                    )

                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_block.id,
                            "content": result_json,
                        }
                    )

                # Append assistant response and tool results
                messages.append({"role": "assistant", "content": response.content})
                messages.append({"role": "user", "content": tool_results})

                # Call API again with tool results
                response = await self.client.messages.create(
                    model=settings.assistant_model,
                    max_tokens=settings.assistant_max_tokens,
                    system=system_prompt,
                    tools=TOOL_DEFINITIONS,
                    messages=messages,
                )

                await self._log_usage(
                    session_id,
                    response.usage.input_tokens,
                    response.usage.output_tokens,
                )

            # Extract final text
            final_text = ""
            for block in response.content:
                if hasattr(block, "text"):
                    final_text += block.text

            if not final_text:
                final_text = "I wasn't able to generate a response. Try rephrasing your question."

        except anthropic.RateLimitError:
            final_text = "I'm getting a lot of questions right now. Try again in a moment."
        except anthropic.APITimeoutError:
            final_text = (
                "That question required a lot of data crunching. "
                "Try asking something more specific."
            )
        except anthropic.APIError as e:
            logger.error(f"Anthropic API error: {e}")
            final_text = "Something went wrong with the AI service. Please try again."

        # Save conversation
        await self._save_message(session_id, "user", user_message)
        await self._save_message(
            session_id,
            "assistant",
            final_text,
            tool_calls=json.dumps(all_tool_calls) if all_tool_calls else None,
            tool_results=json.dumps(all_tool_results, default=str) if all_tool_results else None,
        )

        return {
            "answer": final_text,
            "session_id": session_id,
            "tools_used": tools_used,
        }


# Module-level singleton
fantasy_assistant = FantasyAssistant()
