import tracemalloc, gc, os, sys, cmd, collections.abc


class ID(int):
  '''hashable object wrapper'''

  def __new__(cls, obj):
    self = int.__new__(cls, id(obj))
    self.obj = obj
    return self


def fmtref(obj, ref):
  '''create format string relating `ref` to `obj`

  Aims to make explicit how an object `ref` is referenced by `obj` by means of
  a format string involving {obj:} and {ref:}. For example, if obj.x is ref,
  the format string is "{obj:}.x is {:ref}".'''

  try:
    if isinstance(obj, collections.abc.Mapping):
      for key, value in obj.items():
        if value is ref:
          return '{obj:}[%r] is {ref:}' % key
        if key is ref:
          return '{obj:}[{ref:}]'
    if isinstance(obj, collections.abc.Sequence):
      for i, value in enumerate(obj):
        if value is ref:
          return '{obj:}[%d] is {ref:}' % i
    if isinstance(obj, collections.abc.Set):
      if any(value is ref for value in obj):
        return '{ref:} in {obj:}'
    for attr in dir(obj):
      if getattr(obj, attr) is ref:
        return '{obj:}.%s is {ref:}' % attr
  except:
    pass


def separate(refs):
  '''separate unconnected graphs

  Employs a disjoint-set data structure to separate unconnected graphs of the
  type {a: b, b: a, c: d} into {a: b, b: a} and {c: d}.'''

  rootmap = {}
  union = {}
  for key, vals in refs.items():
    items = {key}
    items.update(vals)
    roots = {rootmap[item] for item in items if item in rootmap}
    if roots:
      root = roots.pop()
      for rmroot in roots:
        items.update(union.pop(rmroot))
      union[root].update(items)
    else:
      root = object()
      union[root] = items
    for item in items:
      rootmap[item] = root
  return [{key: refs[key] for key in s} for s in union.values()]


class explore_cycles(cmd.Cmd):
  '''explore reference cycles interactively

  Separates uncollected objects in cycles and provides a command line interface
  for live exploration, or returns in case no uncollected objects are found.'''

  def __init__(self):
    super().__init__()
    gc.collect()
    garbage = {ID(obj) for obj in gc.garbage}
    print('found {} uncollected objects'.format(len(garbage)))
    if not garbage:
      return
    self.cycles = []
    for cycle in separate({item: garbage.intersection(ID(ref) for ref in gc.get_referents(item.obj)) for item in garbage}):
      size = sum(sys.getsizeof(item.obj) for item in cycle)
      # optional: remove chains of the type A: .__dict__->B, B: ['x'] -> C and replace by A: .x -> C
      for item, refs in cycle.items():
        __dict__ = getattr(item.obj, '__dict__', None)
        if isinstance(__dict__, dict):
          ref = ID(__dict__)
          if ref in cycle[item] and not any(ref in otherrefs for otheritem, otherrefs in cycle.items() if otheritem != item):
            cycle[item] = cycle[ref] | cycle[item] - {ref}
            cycle[ref] = set()
      # remove items that have no outgoing references
      while True:
        remove = {item for item, refs in cycle.items() if not refs}
        if not remove:
          break
        cycle = {item: refs-remove for item, refs in cycle.items() if item not in remove}
      self.cycles.append((size, cycle))
    self.cycles.sort(key=lambda v: (v[0], len(v[1])))
    self.selection = 0
    self.list()
    self.cmdloop()

  def list(self):
    size, cycle = self.cycles[self.selection]
    print('identified {} cycles:'.format(len(self.cycles)), ', '.join(('{}*' if c is cycle else '{}').format(len(c)) for s, c in self.cycles))
    print('selected {} objects ({:.1f}k)'.format(len(cycle), size/1024))
    varnames = 'abcdefghijklmnopqrstuvwxyz'
    while len(varnames) < len(cycle):
      varnames = [a+b for a in varnames for b in varnames]
    varmap = dict(zip(cycle, varnames))
    for item in cycle:
      refs = [(fmtref(item.obj, ref.obj) or '{obj:} -> {ref:}').format(obj=varmap[item], ref=varmap[ref]) for ref in cycle[item]]
      print(varmap[item], type(item.obj), ', '.join(sorted(refs)))
    self.locals = {var: item.obj for item, var in varmap.items()}

  def do_quit(self, arg):
    return True

  def do_list(self, arg):
    self.list()

  def do_next(self, arg):
    self.selection = (self.selection+1) % len(self.cycles)
    self.list()

  def do_previous(self, arg):
    self.selection = (self.selection-1) % len(self.cycles)
    self.list()

  def do_print(self, arg):
    try:
      obj = eval(arg, self.locals)
    except Exception as e:
      print('error:', e)
    else:
      print(obj)

  def do_traceback(self, arg):
    objects = [self.locals.get(name) for name in arg.split() or self.locals]
    if any(object is None for object in objects):
      print('invalid argument {!r}'.format(arg))
      return
    complete = []
    incomplete = []
    for obj in objects:
      tb = tracemalloc._get_object_traceback(obj)
      if tb is not None:
        for i, (path, line) in enumerate(tb):
          if path == __file__:
            complete.append(tb[:i])
            break
        else:
          incomplete.append(tb)
    if complete:
      common = min(complete, key=len)
      while common and any(tb[len(tb)-len(common):] != common for tb in complete):
        common = common[1:]
      print('\n'.join(tracemalloc.Traceback(common).format()))
    elif len(incomplete) > 1:
      print('cannot establish common traceback (try increasing the traceback depth)')
    elif incomplete:
      print('\n'.join(tracemalloc.Traceback(incomplete[0]).format()))
      print('  ...')
    else:
      print('no traceback found')

  # abbreviations
  do_q = do_quit
  do_l = do_list
  do_n = do_next
  do_p = do_print
  do_tb = do_traceback


if __name__ == '__main__':
  if not tracemalloc.is_tracing():
    sys.exit('specify tracing depth using -X tracemalloc=N')
  del sys.argv[0]
  path = sys.argv[0]
  with open(path, 'r') as f:
    src = f.read()
  code = compile(src, path, 'exec')
  gc.set_debug(gc.DEBUG_SAVEALL)
  print('executing {} tracing at depth {}'.format(path, tracemalloc.get_traceback_limit()))
  try:
    exec(code)
  finally:
    explore_cycles()
