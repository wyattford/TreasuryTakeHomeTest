import asyncio

from app.priority_gate import BATCH, INTERACTIVE, PriorityGate


async def _hold(gate: PriorityGate, priority: int, name: str, order: list[str], release: asyncio.Event) -> None:
    async with gate.slot(priority):
        order.append(name)
        await release.wait()


def test_interactive_jumps_ahead_of_queued_batch_work():
    async def scenario():
        gate = PriorityGate(1)
        order: list[str] = []
        release = asyncio.Event()
        tasks = [asyncio.create_task(_hold(gate, BATCH, "batch-running", order, release))]
        await asyncio.sleep(0)
        tasks += [asyncio.create_task(_hold(gate, BATCH, f"batch-{i}", order, release)) for i in range(3)]
        await asyncio.sleep(0)
        tasks.append(asyncio.create_task(_hold(gate, INTERACTIVE, "agent", order, release)))
        await asyncio.sleep(0)
        release.set()
        await asyncio.gather(*tasks)
        return order

    assert asyncio.run(scenario()) == ["batch-running", "agent", "batch-0", "batch-1", "batch-2"]


def test_cancelled_waiter_does_not_leak_its_slot():
    async def scenario():
        gate = PriorityGate(1)
        order: list[str] = []
        release = asyncio.Event()
        holder = asyncio.create_task(_hold(gate, BATCH, "holder", order, release))
        await asyncio.sleep(0)
        doomed = asyncio.create_task(_hold(gate, INTERACTIVE, "doomed", order, release))
        await asyncio.sleep(0)
        doomed.cancel()
        release.set()
        await holder
        await asyncio.wait_for(_hold(gate, BATCH, "after", order, release), timeout=1)
        return order

    assert asyncio.run(scenario()) == ["holder", "after"]
