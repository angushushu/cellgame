"""Run either the game server or player client."""
import sys
from . import __version__


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print("CellGame: python -m cellgame {server,client,contract} [options]\n"
              "  server   Start a world and its web dashboard\n"
              "  client   Start the player console\n"
              "  contract Print the public interface registry (--schema for JSON Schema)\n"
              "Use python -m cellgame server --help or client --help for options.")
        return
    if sys.argv[1] in ("-V", "--version"):
        print(__version__)
        return
    role = sys.argv.pop(1)
    if role == "contract":
        import json
        from .shared.contract import describe_contract, protocol_schema
        print(json.dumps(protocol_schema() if "--schema" in sys.argv else describe_contract(), ensure_ascii=False, indent=2))
        return
    if role == "server":
        from .server.main import main as run
    elif role == "client":
        from .client.main import main as run
    else:
        raise SystemExit(f"Unknown command: {role}. Use server, client or contract.")
    run()


if __name__ == "__main__":
    main()
