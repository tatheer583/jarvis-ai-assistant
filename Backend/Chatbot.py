"""Local chat compatibility API. Text here never becomes a desktop command."""
from Backend.Config import Config
from Backend.Commands import Command
from Backend.Services import Services

_services = None

def ChatBot(Query):
    global _services
    if _services is None:
        _services = Services(Config())
    return _services.execute_command(Command("chat", Query), source="compatibility").message

if __name__ == "__main__":
    import sys
    print(ChatBot(" ".join(sys.argv[1:]) or "hello"))
