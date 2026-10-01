# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
"""M0 capability probe: datetime availability, dataclass storage, TreeMap, json in calldata."""

import json
from dataclasses import dataclass

from genlayer import gl, allow_storage, TreeMap, DynArray, u256


@allow_storage
@dataclass
class Rec:
	id: str
	n: u256
	flag: bool


class ProbeCaps(gl.Contract):
	owner: str
	recs: TreeMap[str, Rec]
	ids: DynArray[str]
	found: u256
	note: str

	def __init__(self) -> None:
		self.owner = "0x" + "aa" * 20
		self.found = u256(0)
		self.note = ""

	@gl.public.write
	def probe(self) -> None:
		notes = []
		try:
			import datetime

			now = gl.message_raw["datetime"]
			dt = datetime.datetime.fromisoformat(now.replace("Z", "+00:00"))
			plus = (dt + datetime.timedelta(seconds=600)).isoformat().replace("+00:00", "Z")
			notes.append(f"datetime OK now={now} plus600={plus}")
		except BaseException as e:  # noqa: BLE001
			notes.append(f"datetime FAIL {type(e).__name__}: {e}")

		try:
			self.recs["a"] = Rec(id="a", n=u256(7), flag=True)
			self.ids.append("a")
			r = self.recs["a"]
			notes.append(f"storage OK recs={len(self.recs)} n={int(r.n)} flag={r.flag} ids={len(self.ids)}")
		except BaseException as e:  # noqa: BLE001
			notes.append(f"storage FAIL {type(e).__name__}: {e}")

		try:
			enc = gl.vm.Return
			notes.append("vm.Return OK")
		except BaseException as e:  # noqa: BLE001
			notes.append(f"vm.Return FAIL {e}")

		notes.append("entry_kind=%s" % gl.message_raw.get("entry_kind"))
		self.note = " || ".join(notes)
		self.found = u256(1)
		gl.trace("CAPS", self.note)
