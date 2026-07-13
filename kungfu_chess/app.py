"""
Main entry point: reads DSL input from stdin and runs it.
Git repository: https://github.com/ayalaDaube/Kung-Fo_Chess
"""
import sys
from kungfu_chess.texttests.script_runner import ScriptRunner


def main():
    script = sys.stdin.read()
    runner = ScriptRunner()
    errors = runner.run(script)
    for e in errors:
        print(e)


if __name__ == "__main__":
    main()
