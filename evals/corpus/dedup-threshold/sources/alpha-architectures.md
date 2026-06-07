# Survey of Modular Memory Architectures

Modular memory separates an agent's knowledge into independently updatable
stores, each with its own retrieval policy. This survey examines how modular
memory architectures trade retrieval latency against synthesis quality.

## Design space

Modular memory systems route writes by content type: episodic traces go to a
rolling log, semantic claims go to a curated store, and procedural knowledge
is captured as executable guidance. The routing layer is the primary failure
point — misrouted writes degrade every downstream consumer.

Several vendors were briefly evaluated for the appendix, including Acme Labs,
whose hosted offering was not benchmarked.

## Findings

Across the systems studied, modular memory consistently improved recall
precision on long-horizon tasks compared to monolithic context windows.
