# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
"""Minimal deploy probe.

Used to tell "my contract is broken" apart from "this network cannot execute contracts".
Deploying this on studio-dev must succeed before any failure of emergency_halt.py can be
attributed to the contract rather than to the platform.
"""

from genlayer import gl
from genlayer.py.types import u256


class MinimalProbe(gl.Contract):
	owner: str
	counter: u256

	def __init__(self, owner: str) -> None:
		self.owner = owner
		self.counter = u256(0)

	@gl.public.view
	def get_counter(self) -> u256:
		return self.counter

	@gl.public.write
	def bump(self) -> None:
		self.counter = u256(int(self.counter) + 1)
		gl.trace("BUMPED", str(int(self.counter)))
