import dis
import types

def calc_insn_size(insn):
	"""Calculate how many bytes the bytecode for the instruction will take"""
	return (6 if insn.arg >= 65536 else 3) if insn.op >= dis.HAVE_ARGUMENT else 1

def encode_insn(insn):
	"""Generate bytecode for the instruction"""
	l = [insn.op]
	if insn.op >= dis.HAVE_ARGUMENT:
		l += [insn.arg & 0xff, (insn.arg >> 8) & 0xff]
		if insn.arg >= 65536:
			l = [dis.EXTENDED_ARG, (insn.arg >> 16) & 0xff, (insn.arg >> 24) & 0xff] + l
	return bytes(l)

def _recalc_insn_offsets(insns):
	"""Calculate the offset of each instruction in the resulting bytecode"""
	offset = 0
	for insn in insns:
		insn.offset = offset
		offset += calc_insn_size(insn)
	return offset

def _recalc_jump_offsets(insns):
	"""Calculate the target offset of each jump instruction

	Return value tells whether this caused the encoding of any jump instruction to change in size
	"""
	size_changed = 0
	for insn in insns:
		size = calc_insn_size(insn)
		if insn.op in dis.hasjabs:
			insn.arg = insn.target.offset
			insn.argval = insn.target.offset
		elif insn.op in dis.hasjrel:
			insn.arg = insn.target.offset - (insn.offset + size)
			insn.argval = insn.target.offset
		new_size = calc_insn_size(insn)
		if new_size != size:
			size_changed += 1
	return size_changed

def _reset_jump_offsets(insns):
	"""Reset all jump target offsets to 0 (so that jumps will use the smaller encoding by default)"""
	for insn in insns:
		if insn.op in hasjump:
			insn.arg = 0

def fix_offsets(insns):
	"""Calculate all instruction and jump target offsets"""
	size = _recalc_insn_offsets(insns)
	_reset_jump_offsets(insns)
	# Updating the jump target offsets might cause the encoding size of some jump instructions to grow
	# If that happens, we have to recalculate the instruction offsets, some of which have grown, which means
	# we have to update the jump targets again. Naturally, this has to be repeated until things settle down.
	while _recalc_jump_offsets(insns):
		size = _recalc_insn_offsets(insns)
	return size

def calc_lnotab(insns, firstlineno=0):
	"""Calculate the line number table for the bytecode"""
	# Details of the format of co_lnotab are explained in Objects/lnotab_notes.txt, so I won't bother repeating all of that
	new_lnotab = []
	prev_offset, prev_lineno = 0, firstlineno
	for insn in insns:
		if insn.starts_line:
			offset, lineno = insn.offset - prev_offset, insn.starts_line - prev_lineno
			prev_offset, prev_lineno = insn.offset, insn.starts_line
			assert (offset > 0 or prev_offset == 0) and lineno > 0
			while offset > 255:
				new_lnotab.extend((255, 0))
				offset -= 255
			while lineno > 255:
				new_lnotab.extend((offset, 255))
				offset = 0
				lineno -= 255
			new_lnotab.extend((offset, lineno))
	return bytes(new_lnotab)

class Instruction:
	def __init__(self, name, op, arg=None, argval=None, argrepr=None, offset=None, starts_line=None, is_jump_target=False):
		self.name = name
		self.op = op
		self.arg = arg
		self.argval = argval
		self.argrepr = argrepr
		self.offset = offset
		self.starts_line = starts_line
		self.is_jump_target = is_jump_target
		self.target = None

hasjump = set(dis.hasjrel + dis.hasjabs)
def get_instructions(func):
	"""Get the bytecode for the function, in a mutable format, with jump target links"""
	insns = [Instruction(*insn) for insn in dis.get_instructions(func)]
	insn_map = {insn.offset: insn for insn in insns}

	for insn in insns:
		if insn.op in hasjump:
			insn.target = insn_map[insn.argval]
			assert insn.target.is_jump_target

	return insns

def new_insn(name, arg=None, argval=None, starts_line=None, is_jump_target=False):
	return Instruction(name, dis.opmap[name], arg, argval, None, None, starts_line, is_jump_target)

def yieldify(func):
	co = func.__code__
	insns = get_instructions(func)

	# Add yields to the bytecode
	yieldno = 1
	new_consts = list(co.co_consts)
	new_insns = []
	for insn in insns:
		if insn.starts_line is not None and insn.offset:
			try:
				arg = new_consts.index(yieldno)
			except ValueError:
				arg = len(new_consts)
				new_consts.append(yieldno)
			yieldno += 1
			new_insns.extend([
				new_insn('LOAD_CONST', arg),
				new_insn('YIELD_VALUE'),
				new_insn('POP_TOP'),
			])
		new_insns.append(insn)

	fix_offsets(new_insns)
	new_lnotab = calc_lnotab(new_insns, co.co_firstlineno)
	new_bytecode = b''.join(map(encode_insn, new_insns))

	new_code = types.CodeType(
		co.co_argcount,
		co.co_kwonlyargcount,
		co.co_nlocals,
		# To be safe (the stack should usually be empty at points where we yield)
		co.co_stacksize + 1,
		# We added yields, so the function is a generator now
		co.co_flags | 0x20,
		new_bytecode,
		tuple(new_consts),
		co.co_names,
		co.co_varnames,
		co.co_filename,
		co.co_name,
		co.co_firstlineno,
		new_lnotab,
		co.co_freevars,
		co.co_cellvars,
	)

	new_func = types.FunctionType(
		new_code,
		func.__globals__,
		func.__name__,
		func.__defaults__,
		func.__closure__,
	)

	return new_func

if __name__ == '__main__':
	from . import target

	func = yieldify(target.target)

	for i in func(0):
		print('yield', i)

