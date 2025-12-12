# Weighted Round Robin Arbiter with Atomic Lock Support

## Overview

This repository contains a Reinforcement Learning (RL) task for hardware design agents. The goal is to design a **Weighted Round Robin (WRR) Arbiter** that supports **Atomic Locking**. This component is a critical building block for high-performance bus interconnects and Network-on-Chip (NoC) routers.

## Motivation: Why this Task?

We chose this task to specifically target known weaknesses in current Large Language Models (LLMs) when generating Register Transfer Level (RTL) code. While simple Round Robin arbiters are common in training data, adding **conflicting constraints** (weights vs. locks) creates a "reasoning trap" that effectively measures an agent's ability to handle stateful logic.

Key challenges this task presents to an agent:

  * **State Conflict Management:** The agent must correctly prioritize between a "weight counter" (expiration) and a "lock signal" (override). LLMs often hallucinate race conditions here.
  * **Work Conservation:** The specification requires immediate switching if a client drops a request early. This tests the agent's ability to implement efficient, non-idle logic rather than blindly waiting for counters to expire.
  * **Security & Permissions:** The strict requirement that *only* the current owner can lock the bus tests the agent's ability to implement conditional logic and prevent unauthorized access (lock stealing).

## Industry Relevance

In modern semiconductor design, arbitration is rarely as simple as "fair rotation."

  * **Quality of Service (QoS):** Real-world systems (like AXI4 Interconnects or PCIe switches) must prioritize high-bandwidth agents (e.g., DMA controllers) over low-bandwidth agents (e.g., configuration masters). This is modeled here via the `i_weight` parameter.
  * **Atomic Operations:** Processors and accelerators frequently need to perform **Read-Modify-Write (RMW)** sequences that cannot be interrupted. The `i_lock` signal mimics this requirement, allowing an agent to hold the bus indefinitely to complete a critical section.

## Context Codebase Description

The repository is structured to mimic a standard hardware development environment.

| Directory / File | Description |
| :--- | :--- |
| **`sources/`** | Contains the SystemVerilog RTL source code. |
| `sources/arbiter_wrr_lock.sv` | The target design file. The agent must implement the logic here. |
| **`tests/`** | Contains the verification environment. |
| `tests/test_arbiter_hidden.py` | The hidden `cocotb` testbench used to grade the agent. It tests edge cases like illegal locking, early termination, and counter overflows. |
| **`docs/`** | Contains the technical documentation. |
| `docs/specification.md` | The detailed functional specification, interface definitions, and timing requirements that the agent must adhere to. |
| **Root** | |
| `prompt.txt` | The high-level task description provided to the agent/engineer. |
| `pyproject.toml` | Python dependencies required to run the `cocotb` simulations. |
