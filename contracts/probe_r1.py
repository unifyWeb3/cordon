# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
"""
M0b probe (R1): does gl.evm.contract_interface View/emit work under local GLSim?

Isolated so the R1 answer does not contaminate the product contract.
Two SDK gotchas encoded here (neither shown in the published docs):
  * View/Write methods must declare positional-only params (`/`).
  * Exactly one `gl.Contract` subclass per module.
"""

from genlayer import gl
from genlayer.py.types import Address, u256


class Target:
	class View:
		def is_frozen(self, /) -> bool: ...

	class Write:
		def freeze(self, reason: str, until: u256, /) -> None: ...


target_intf = gl.evm.contract_interface(Target)


class Probe(gl.Contract):
	target: str
	view_ok: u256
	emit_ok: u256
	detail: str

	def __init__(self, target: Address) -> None:
		self.target = target
		self.view_ok = u256(0)
		self.emit_ok = u256(0)
		self.detail = "not-run"

	@gl.public.write
	def read_target(self) -> None:
		proxy = target_intf(Address(self.target))
		detail = "no-exception"
		try:
			v = proxy.view().is_frozen()
			self.view_ok = u256(1)
			detail = f"view returned {v!r}"
		except BaseException as e:  # noqa: BLE001
			detail = f"view raised {type(e).__name__}: {e}"
		try:
			proxy.emit().freeze("probe", u256(1))
			self.emit_ok = u256(1)
			detail = detail + " | emit ok"
		except BaseException as e:  # noqa: BLE001
			detail = detail + f" | emit raised {type(e).__name__}: {e}"
		self.detail = detail
		gl.trace("PROBE", detail)
