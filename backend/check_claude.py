"""Test rapide API Claude + fallback chain."""
import asyncio, sys, os
os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from adapters.llm.claude_haiku_adapter import ClaudeHaikuAdapter

async def main():
    adapter = ClaudeHaikuAdapter()
    try:
        resp = await adapter.generate(
            system="Tu es un assistant concis.",
            user="Reponds juste: API OK",
            max_tokens=20
        )
        print(f"Claude Haiku: {resp}")
        print("STATUS: Claude API operationnelle!")
    except Exception as e:
        err = str(e).lower()
        if "overloaded" in err:
            print(f"Claude API: SURCHARGEE (overloaded) - fallback Ollama actif")
        elif "insufficient_quota" in err:
            print(f"Claude API: QUOTA EPUISE - fallback Ollama actif")
        else:
            print(f"Claude API: ERREUR - {e}")

asyncio.run(main())
