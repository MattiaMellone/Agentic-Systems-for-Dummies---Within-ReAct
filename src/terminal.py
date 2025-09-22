"""Terminal module.
Provides functions: _timezone, _today_iso_local, colorize, build_agent, main.

This code is organized for readability, maintainability, and testability."""

from __future__ import annotations
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo
import dotenv
from colorama import Fore, Style, init
from src.agent import ReActAgent, ToolSpec
from src.tools import date_math, tavily_search, openmeteo_forecast, openmeteo_archive
from src.schemas import DATE_MATH_SCHEMA, TAVILY_SEARCH_SCHEMA, OPENMETEO_FORECAST_SCHEMA, OPENMETEO_ARCHIVE_SCHEMA

def _timezone() -> ZoneInfo:
    """Timezone.

Returns:
    Return value."""
    tz_name = os.getenv('TIMEZONE', 'Europe/Rome').strip() or 'Europe/Rome'
    try:
        return ZoneInfo(tz_name)
    except Exception:
        return ZoneInfo('Europe/Rome')

def _today_iso_local() -> str:
    """Today iso local.

Returns:
    Return value."""
    tz = _timezone()
    return datetime.now(tz).strftime('%Y-%m-%d')

def colorize(line: str) -> str:
    """Colorize.

Args:
    line: Input parameter.
Returns:
    Return value."""
    s = line.strip()
    if s.startswith('Plan:'):
        return Fore.BLUE + Style.BRIGHT + line + Style.RESET_ALL
    if s.startswith('Confirm:'):
        return Fore.YELLOW + line + Style.RESET_ALL
    if s.startswith('Check-Final:'):
        return Fore.YELLOW + Style.DIM + line + Style.RESET_ALL
    if s.startswith('Action:'):
        return Fore.CYAN + line + Style.RESET_ALL
    if s.startswith('Action Input:'):
        return Fore.CYAN + '  ' + line + Style.RESET_ALL
    if s.startswith('Observation:'):
        return Fore.MAGENTA + line + Style.RESET_ALL
    if s.startswith('Final Answer:'):
        return Fore.GREEN + Style.BRIGHT + line + Style.RESET_ALL
    return line

def build_agent() -> ReActAgent:
    """Build agent.

Returns:
    Return value."""
    tools = [ToolSpec(name='date_math', description='Calculate date offsets and intervals (LLM-based parsing).', args_schema=DATE_MATH_SCHEMA, func=date_math), ToolSpec(name='tavily_search', description='Perform a web search using Tavily API.', args_schema=TAVILY_SEARCH_SCHEMA, func=tavily_search), ToolSpec(name='openmeteo_forecast', description='Weather forecast using Open-Meteo (exact target_date or days window, max 16 days).', args_schema=OPENMETEO_FORECAST_SCHEMA, func=openmeteo_forecast), ToolSpec(name='openmeteo_archive', description='Historical daily weather via Open-Meteo ERA5 (max 31 days).', args_schema=OPENMETEO_ARCHIVE_SCHEMA, func=openmeteo_archive)]
    return ReActAgent(tools=tools)

def main() -> None:
    """Main.

Returns:
    Return value."""
    dotenv.load_dotenv()
    init(autoreset=True)
    tz_name = os.getenv('TIMEZONE', 'Europe/Rome').strip() or 'Europe/Rome'
    today_iso = _today_iso_local()
    print(Fore.BLUE + Style.BRIGHT + '=== ReAct Agent REPL ===' + Style.RESET_ALL)
    print(f'[Env] Today is {Fore.YELLOW}{today_iso}{Style.RESET_ALL} (Timezone: {Fore.CYAN}{tz_name}{Style.RESET_ALL})')
    print("Type your question, or 'exit' to quit.")
    agent = build_agent()
    while True:
        try:
            user_in = input(Fore.BLUE + '\nYou> ' + Style.RESET_ALL).strip()
        except (EOFError, KeyboardInterrupt):
            print('\nBye!')
            break
        if not user_in:
            continue
        if user_in.lower() in {'exit', 'quit'}:
            break
        try:
            print(Fore.BLUE + Style.BRIGHT + '\n--- Agent Trace ---' + Style.RESET_ALL)

            def on_step(line: str) -> None:
                """On step.

Args:
    line: Input parameter.
Returns:
    Return value."""
                print(colorize(line))
            final = agent.run(user_in, on_step=on_step)
            print(Fore.GREEN + Style.BRIGHT + '\n=== Final Answer ===' + Style.RESET_ALL)
            print(Fore.GREEN + final + Style.RESET_ALL)
        except Exception as e:
            print(Fore.RED + f'[ERROR] {e}' + Style.RESET_ALL, file=sys.stderr)
if __name__ == '__main__':
    main()
