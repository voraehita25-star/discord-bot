#!/usr/bin/env python
"""
Load Testing Script for Discord Bot AI.
Simulates concurrent AI requests to measure performance.

Usage:
    python scripts/load_test.py --requests 100 --concurrency 10
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import time
from dataclasses import dataclass, field


@dataclass
class LoadTestResult:
    """Results from a load test."""

    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    latencies: list[float] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    start_time: float = 0
    end_time: float = 0

    @property
    def success_rate(self) -> float:
        if self.total_requests == 0:
            return 0
        return self.successful_requests / self.total_requests

    @property
    def avg_latency(self) -> float:
        if not self.latencies:
            return 0
        return statistics.mean(self.latencies)

    @property
    def p50_latency(self) -> float:
        if not self.latencies:
            return 0
        return statistics.median(self.latencies)

    @property
    def p95_latency(self) -> float:
        if not self.latencies:
            return 0
        sorted_latencies = sorted(self.latencies)
        idx = int(len(sorted_latencies) * 0.95)
        return sorted_latencies[min(idx, len(sorted_latencies) - 1)]

    @property
    def p99_latency(self) -> float:
        if not self.latencies:
            return 0
        sorted_latencies = sorted(self.latencies)
        idx = int(len(sorted_latencies) * 0.99)
        return sorted_latencies[min(idx, len(sorted_latencies) - 1)]

    @property
    def duration(self) -> float:
        return self.end_time - self.start_time

    @property
    def requests_per_second(self) -> float:
        if self.duration == 0:
            return 0
        return self.total_requests / self.duration

    def print_summary(self) -> None:
        """Print test results summary."""
        print("\n" + "=" * 60)
        print("LOAD TEST RESULTS")
        print("=" * 60)
        print(f"Total Requests:    {self.total_requests}")
        print(f"Successful:        {self.successful_requests}")
        print(f"Failed:            {self.failed_requests}")
        print(f"Success Rate:      {self.success_rate:.1%}")
        print("-" * 60)
        print(f"Total Duration:    {self.duration:.2f}s")
        print(f"Requests/sec:      {self.requests_per_second:.2f}")
        print("-" * 60)
        print("LATENCY (seconds):")
        print(f"  Average:         {self.avg_latency:.3f}")
        print(f"  Median (p50):    {self.p50_latency:.3f}")
        print(f"  p95:             {self.p95_latency:.3f}")
        print(f"  p99:             {self.p99_latency:.3f}")
        if self.latencies:
            print(f"  Min:             {min(self.latencies):.3f}")
            print(f"  Max:             {max(self.latencies):.3f}")
        print("=" * 60)

        if self.errors:
            print(f"\nErrors ({len(self.errors)}):")
            for err in self.errors[:5]:
                print(f"  - {err[:100]}")


async def simulate_ai_request(
    request_id: int, result: LoadTestResult, simulate_delay: float = 0.5
) -> None:
    """
    Simulate an AI request.

    In a real test, this would call the actual AI endpoint.
    For now, it simulates with random delays.
    """
    import random

    start_time = time.perf_counter()

    try:
        # Simulate processing time (in real test, call actual API)
        delay = random.uniform(simulate_delay * 0.5, simulate_delay * 2)
        await asyncio.sleep(delay)

        # Simulate occasional failures (5% chance)
        if random.random() < 0.05:
            raise Exception(f"Simulated failure for request {request_id}")

        latency = time.perf_counter() - start_time
        result.latencies.append(latency)
        result.successful_requests += 1

    except Exception as e:
        result.errors.append(str(e))
        result.failed_requests += 1

    result.total_requests += 1


async def run_load_test(
    total_requests: int = 100, concurrency: int = 10, simulate_delay: float = 0.5
) -> LoadTestResult:
    """
    Run load test with specified parameters.

    Args:
        total_requests: Total number of requests to make
        concurrency: Number of concurrent requests
        simulate_delay: Base delay for simulated requests

    Returns:
        LoadTestResult with test statistics
    """
    result = LoadTestResult()
    result.start_time = time.time()

    print("Starting load test...")
    print(f"  Total requests: {total_requests}")
    print(f"  Concurrency: {concurrency}")
    print(f"  Simulated delay: {simulate_delay}s")

    # Create semaphore for concurrency control
    semaphore = asyncio.Semaphore(concurrency)

    async def rate_limited_request(req_id: int) -> None:
        async with semaphore:
            await simulate_ai_request(req_id, result, simulate_delay)
            if req_id % 10 == 0:
                print(f"  Completed {req_id}/{total_requests} requests...")

    # Run all requests
    tasks = [rate_limited_request(i) for i in range(1, total_requests + 1)]
    await asyncio.gather(*tasks)

    result.end_time = time.time()
    return result


async def run_rate_limiter_test(
    burst_size: int = 20, delay_between_bursts: float = 1.0, total_bursts: int = 5
) -> None:
    """
    Test rate limiter behavior under burst loads.
    """
    print("\n" + "=" * 60)
    print("RATE LIMITER TEST")
    print("=" * 60)

    try:
        from utils.reliability.rate_limiter import rate_limiter

        allowed_count = 0
        blocked_count = 0

        for burst in range(total_bursts):
            print(f"\nBurst {burst + 1}/{total_bursts}:")

            for _i in range(burst_size):
                allowed, _retry, _ = await rate_limiter.check("gemini_api", user_id=12345)

                if allowed:
                    allowed_count += 1
                else:
                    blocked_count += 1

            print(f"  Allowed: {allowed_count}, Blocked: {blocked_count}")

            if burst < total_bursts - 1:
                print(f"  Waiting {delay_between_bursts}s...")
                await asyncio.sleep(delay_between_bursts)

        print(f"\nTotal: {allowed_count} allowed, {blocked_count} blocked")
        print(f"Block rate: {blocked_count / (allowed_count + blocked_count):.1%}")

    except ImportError:
        print("Rate limiter not available")


async def run_circuit_breaker_test(failure_count: int = 10) -> None:
    """
    Test circuit breaker behavior.
    """
    print("\n" + "=" * 60)
    print("CIRCUIT BREAKER TEST")
    print("=" * 60)

    try:
        from utils.reliability.circuit_breaker import gemini_circuit

        print(f"Initial state: {gemini_circuit.state.value}")

        # Simulate failures
        print(f"\nSimulating {failure_count} failures...")
        for _i in range(failure_count):
            gemini_circuit.record_failure()

        print(f"After failures: {gemini_circuit.state.value}")
        print(f"Can execute: {gemini_circuit.can_execute()}")

        # Reset
        gemini_circuit.reset()
        print(f"After reset: {gemini_circuit.state.value}")

    except ImportError:
        print("Circuit breaker not available")


def main():
    parser = argparse.ArgumentParser(description="Load test the Discord bot AI")
    parser.add_argument(
        "--requests", "-r", type=int, default=100, help="Total number of requests to make"
    )
    parser.add_argument(
        "--concurrency", "-c", type=int, default=10, help="Number of concurrent requests"
    )
    parser.add_argument(
        "--delay", "-d", type=float, default=0.5, help="Simulated request delay in seconds"
    )
    parser.add_argument("--test-rate-limiter", action="store_true", help="Also test rate limiter")
    parser.add_argument(
        "--test-circuit-breaker", action="store_true", help="Also test circuit breaker"
    )

    args = parser.parse_args()

    async def run_all():
        # Main load test
        result = await run_load_test(
            total_requests=args.requests, concurrency=args.concurrency, simulate_delay=args.delay
        )
        result.print_summary()

        # Optional tests
        if args.test_rate_limiter:
            await run_rate_limiter_test()

        if args.test_circuit_breaker:
            await run_circuit_breaker_test()

    asyncio.run(run_all())


if __name__ == "__main__":
    main()
