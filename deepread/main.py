import asyncio
import json
import pprint

from agent import Agent, _print_event

async def _test_run_agent() -> None:
    agent = Agent()

    result = await agent.identify_key_sections("./../papers/controlnext.pdf")
    if result is not None:
        print(f"********* Key Sections *********")
        pprint.pprint(result)
        print(f"********* End Key Sections *********")
        with open("key_sections.json", "w") as f:
            json.dump(result, f, indent=4)
        try:
            code_result = await agent.map_key_sections_to_code(result, "./../code/ControlNeXt")
        except asyncio.CancelledError as e:
            # Surface SDK cancellation in a clearer way instead of an opaque traceback
            print("map_key_sections_to_code was cancelled:", repr(e))
            return
        except Exception as e:
            # Catch and display any other errors from the mapping step
            print("Error while mapping key sections to code:", repr(e))
            return

        if code_result is not None:
            print(f"********* Code Snippets *********")
            pprint.pprint(code_result)
            with open("code_result.json", "w") as f:
                json.dump(code_result, f, indent=4)
            print(f"********* End Code Snippets *********")
        else:
            print("No result found from map_key_sections_to_code")
    else:
        print("No result found")


async def _test_stream_run_agent() -> None:
    agent = Agent(stream_events=True)
    # Methods return the final result; pass on_event to stream all events
    key_sections = await agent.identify_key_sections(
        "./../papers/controlnext.pdf", on_event=_print_event
    )
    if key_sections is None:
        print("No key sections found")
        return
    print("FINAL key_sections:", key_sections)
    code_result = await agent.map_key_sections_to_code(
        key_sections, "./../code/ControlNeXt", on_event=_print_event
    )
    print("FINAL code_result:", code_result)


if __name__ == "__main__":
    asyncio.run(_test_run_agent())