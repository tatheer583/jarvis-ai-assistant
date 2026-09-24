"""Browser search compatibility API; opening a search is an online operation."""
from Backend.Commands import Command, parse_command
from Backend.Config import Config
from Backend.Services import Services

def RealtimeSearchEngine(query):
    service = Services(Config())
    command = parse_command(query)
    if command.action not in {"time", "date"}:
        command = Command("web", query)
    return service.execute_command(command, source="compatibility").message
