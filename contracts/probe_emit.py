# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
"""M0b probe (part 2): does `gl.evm.contract_interface(...).emit()` reach a real EVM contract?

Isolated from emergency_halt.py on purpose. The product only emits a freeze when consensus
returns CONFIRMED_EXPLOIT, and manufacturing an exploit verdict just to exercise the transport
would be dishonest. This probe calls the exact same emit path directly, so the transport can be
tested without faking evidence.

How to read the result -- this matters:

  Under local GLSim, `emit()` is a VERIFIED NO-OP. gltest's WASI mock has no `EthSend` branch, so
  `gl_call` returns a sentinel that `gl_call_generic` maps to `Lazy(lambda: None)`, and
  `_generate_send` returns it without raising. It reports success and does nothing. An assertion
  that the emit "worked" locally would pass green and prove nothing.

  So the only meaningful test is on a real GenVM node, with the answer read from the TARGET
  chain afterwards. That is what this probe is for.
"""

from genlayer import gl, u256
from genlayer.py.types import Address


class Target:
	"""Exactly the interface in emergency_halt.py -- positional-only params required by the SDK."""

	class View:
		def isFrozen(self, /) -> bool: ...

	class Write:
		def freeze(self, reason: str, until: u256, /) -> None: ...
		def unfreeze(self, reason: str, /) -> None: ...


target_intf = gl.evm.contract_interface(Target)


class ProbeEmit(gl.Contract):
	owner: str
	freeze_calls: u256
	unfreeze_calls: u256
	traces: str

	def __init__(self, owner: str) -> None:
		self.owner = owner
		self.freeze_calls = u256(0)
		self.unfreeze_calls = u256(0)
		self.traces = ""

	def _only_owner(self) -> None:
		if gl.message.sender_address.as_hex.lower() != self.owner.lower():
			raise gl.vm.UserError("only owner may do this")

	@gl.public.write
	def emit_freeze(self, target: str, reason: str, until: u256) -> None:
		"""Emit a freeze to `target`. Deliberately outside any nondet block.

		EVM messages are only emitted on finality, and cross-contract/EVM ops are forbidden
		inside a nondet block, so the product does this after run_nondet returns. Same here.
		"""
		self._only_owner()
		trace = ""
		try:
			target_intf(Address(target)).emit().freeze(reason, until)
			self.freeze_calls = u256(int(self.freeze_calls) + 1)
			trace = "EMIT_RETURNED"
		except BaseException as e:  # noqa: BLE001
			trace = f"EMIT_RAISED:{type(e).__name__}"
		self.traces = trace
		gl.trace("PROBE_EMIT", f"{target} {trace}")

	@gl.public.write
	def emit_unfreeze(self, target: str, reason: str) -> None:
		self._only_owner()
		trace = ""
		try:
			target_intf(Address(target)).emit().unfreeze(reason)
			self.unfreeze_calls = u256(int(self.unfreeze_calls) + 1)
			trace = "EMIT_RETURNED"
		except BaseException as e:  # noqa: BLE001
			trace = f"EMIT_RAISED:{type(e).__name__}"
		self.traces = trace
		gl.trace("PROBE_UNFREEZE", f"{target} {trace}")

	@gl.public.view
	def get_traces(self) -> str:
		return self.traces

	@gl.public.view
	def get_counts(self) -> str:
		return f"freeze={int(self.freeze_calls)} unfreeze={int(self.unfreeze_calls)}"
