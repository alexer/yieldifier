import ast
import math

def target(n):
	print('line 1')
	print('line 2')
	for i in range(3):
		print('line 4')
		print('line 5')
	print('line 6')
	math.pi / n

def getmaxloc(node):
	loc = None
	for node_ in ast.walk(node):
		if not hasattr(node_, 'lineno') or not hasattr(node_, 'col_offset'):
			continue
		loc_ = (node_.lineno, node_.col_offset)
		if loc is None or loc_ > loc:
			loc = loc_
	return loc

class Yieldifier(ast.NodeTransformer):
	def __init__(self):
		ast.NodeTransformer.__init__(self)
		self.added = 0

	def generic_visit(self, node):
		ast.NodeTransformer.generic_visit(self, node)
		if isinstance(node, ast.stmt):
			self.added += 1
			return [node, ast.Expr(value=ast.Yield(value=ast.Num(n=self.added)), lineno=getmaxloc(node)[0])]
		else:
			return node

def yieldify(path, func_name):
	with open(path, 'rb') as f:
		source = f.read()

	mod_tree = ast.parse(source, path)
	func_trees = {obj.name: obj for obj in mod_tree.body if isinstance(obj, ast.FunctionDef)}
	func_tree = func_trees[func_name]

	Yieldifier().visit(func_tree)
	ast.fix_missing_locations(func_tree)

	env = {}
	exec(compile(mod_tree, path, 'exec'), env)

	return env[func_name]

if __name__ == '__main__':
	func = yieldify(__file__, 'target')

	for i in func(0):
		print('yield', i)

