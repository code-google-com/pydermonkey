import gc
import sys
import unittest
import weakref
import time
import threading

import pymonkey

class PymonkeyTests(unittest.TestCase):
    def setUp(self):
        self._teardowns = []

    def tearDown(self):
        self.last_exception = None
        while self._teardowns:
            obj = self._teardowns.pop()
            runtime = obj.get_runtime()
            runtime.new_context().clear_object_private(obj)
            del runtime
            del obj
        self.assertEqual(pymonkey.get_debug_info()['runtime_count'], 0)

    def _clearOnTeardown(self, obj):
        self._teardowns.append(obj)

    def _evaljs(self, code):
        rt = pymonkey.Runtime()
        cx = rt.new_context()
        obj = cx.new_object()
        cx.init_standard_classes(obj)
        return cx.evaluate_script(obj, code, '<string>', 1)

    def _execjs(self, code):
        rt = pymonkey.Runtime()
        cx = rt.new_context()
        obj = cx.new_object()
        cx.init_standard_classes(obj)
        script = cx.compile_script(code, '<string>', 1)
        return cx.execute_script(obj, script)

    def _evalJsWrappedPyFunc(self, func, code):
        cx = pymonkey.Runtime().new_context()
        obj = cx.new_object()
        cx.init_standard_classes(obj)
        jsfunc = cx.new_function(func, func.__name__)
        self._clearOnTeardown(jsfunc)
        cx.define_property(obj, func.__name__, jsfunc)
        return cx.evaluate_script(obj, code, '<string>', 1)

    def assertRaises(self, exctype, func, *args):
        was_raised = False
        try:
            func(*args)
        except exctype, e:
            self.last_exception = e
            was_raised = True
        self.assertTrue(was_raised)

    def testSyntaxErrorsAreRaised(self):
        for run in [self._evaljs, self._execjs]:
            self.assertRaises(pymonkey.error, run, '5f')
            self.assertEqual(
                self.last_exception.args[1],
                u'SyntaxError: missing ; before statement'
                )

    def testGetStackOnEmptyStackReturnsNone(self):
        cx = pymonkey.Runtime().new_context()
        self.assertEqual(cx.get_stack(), None)

    def testGetStackWorks(self):
        stack_holder = []

        def func(cx, this, args):
            stack_holder.append(cx.get_stack())

        cx = pymonkey.Runtime().new_context()
        obj = cx.new_object()
        cx.init_standard_classes(obj)
        jsfunc = cx.new_function(func, func.__name__)
        self._clearOnTeardown(jsfunc)
        cx.define_property(obj, func.__name__, jsfunc)
        cx.evaluate_script(obj, 'func()', '<string>', 1)
        script = stack_holder[0]['caller']['script']
        pc = stack_holder[0]['caller']['pc']
        self.assertEqual(script.filename, '<string>')
        self.assertEqual(stack_holder[0]['caller']['lineno'], 1)
        self.assertTrue(pc >= 0 and pc < len(buffer(script)))
        self.assertEqual(stack_holder[0]['caller']['caller'], None)

    def testScriptHasFilenameMember(self):
        cx = pymonkey.Runtime().new_context()
        script = cx.compile_script('foo', '<string>', 1)
        self.assertEqual(script.filename, '<string>')

    def testScriptHasLineInfo(self):
        cx = pymonkey.Runtime().new_context()
        script = cx.compile_script('foo\nbar', '<string>', 1)
        self.assertEqual(script.base_lineno, 1)
        self.assertEqual(script.line_extent, 2)

    def testScriptIsExposedAsBuffer(self):
        rt = pymonkey.Runtime()
        cx = rt.new_context()
        script = cx.compile_script('foo', '<string>', 1)
        self.assertTrue(len(buffer(script)) > 0)

    def testCompileScriptWorks(self):
        self.assertEqual(self._execjs('5 + 1'), 6)

    def testErrorsRaisedIncludeStrings(self):
        self.assertRaises(pymonkey.error, self._evaljs, 'boop()')
        self.assertEqual(self.last_exception.args[1],
                         u'ReferenceError: boop is not defined')

    def testThreadSafetyExceptionIsRaised(self):
        stuff = {}
        def make_runtime():
            stuff['rt'] = pymonkey.Runtime()
        thread = threading.Thread(target = make_runtime)
        thread.start()
        thread.join()
        self.assertRaises(pymonkey.error,
                          stuff['rt'].new_context)
        self.assertEqual(self.last_exception.args[0],
                         'Function called from wrong thread')
        del stuff['rt']

    def testClearObjectPrivateWorks(self):
        class Foo(object):
            pass
        pyobj = Foo()
        cx = pymonkey.Runtime().new_context()
        obj = cx.new_object(pyobj)
        pyobj = weakref.ref(pyobj)
        self.assertEqual(pyobj(), cx.get_object_private(obj))
        cx.clear_object_private(obj)
        self.assertEqual(cx.get_object_private(obj), None)
        self.assertEqual(pyobj(), None)

    def testGetObjectPrivateWorks(self):
        class Foo(object):
            pass
        pyobj = Foo()
        cx = pymonkey.Runtime().new_context()
        obj = cx.new_object(pyobj)
        pyobj = weakref.ref(pyobj)
        self.assertEqual(pyobj(), cx.get_object_private(obj))
        del obj
        del cx
        self.assertEqual(pyobj(), None)

    def testContextSupportsCyclicGc(self):
        def makecx():
            cx = pymonkey.Runtime().new_context()

            def opcb(othercx):
                return cx

            cx.set_operation_callback(opcb)
            return cx

        gc.disable()
        cx = makecx()
        wcx = weakref.ref(cx)
        self.assertEqual(wcx(), cx)
        del cx
        self.assertTrue(wcx())
        gc.enable()
        gc.collect()
        self.assertEqual(wcx(), None)

    def testOperationCallbackIsCalled(self):
        def opcb(cx):
            raise Exception("stop eet!")

        cx = pymonkey.Runtime().new_context()
        cx.set_operation_callback(opcb)
        obj = cx.new_object()
        cx.init_standard_classes(obj)

        def watchdog():
            time.sleep(0.1)
            cx.trigger_operation_callback()

        thread = threading.Thread(target = watchdog)
        thread.start()

        self.assertRaises(
            pymonkey.error,
            cx.evaluate_script,
            obj, 'while (1) {}', '<string>', 1
            )

    def testUndefinedStrIsUndefined(self):
        self.assertEqual(str(pymonkey.undefined),
                         "pymonkey.undefined")

    def testJsWrappedPythonFuncHasPrivate(self):
        def foo(cx, this, args):
            pass

        cx = pymonkey.Runtime().new_context()
        jsfunc = cx.new_function(foo, foo.__name__)
        self.assertEqual(cx.get_object_private(jsfunc), foo)

    def testJsWrappedPythonFuncIsNotGCd(self):
        def define(cx, obj):
            def func(cx, this, args):
                return u'func was called'
            jsfunc = cx.new_function(func, func.__name__)
            cx.define_property(obj, func.__name__, jsfunc)
            return weakref.ref(func)
        rt = pymonkey.Runtime()
        cx = rt.new_context()
        obj = cx.new_object()
        cx.init_standard_classes(obj)
        ref = define(cx, obj)
        cx.gc()
        self.assertNotEqual(ref(), None)
        result = cx.evaluate_script(obj, 'func()', '<string>', 1)
        self.assertEqual(result, u'func was called')

        # Now ensure that the wrapped function is GC'd when it's
        # no longer reachable from JS space.
        cx.define_property(obj, 'func', 0)
        cx.gc()
        self.assertEqual(ref(), None)

    def testCircularJsWrappedPythonFuncIsGCdIfPrivateCleared(self):
        def define(cx, obj):
            rt = cx.get_runtime()
            def func(cx, this, args):
                # Oh noes, a circular reference is born!
                rt
            jsfunc = cx.new_function(func, func.__name__)
            cx.define_property(obj, func.__name__, jsfunc)
            return (jsfunc, weakref.ref(func))
        rt = pymonkey.Runtime()
        cx = rt.new_context()
        obj = cx.new_object()
        cx.init_standard_classes(obj)
        jsfunc, ref = define(cx, obj)

        # This will break the circular reference.
        cx.clear_object_private(jsfunc)

        del jsfunc
        del rt
        del cx
        del obj
        self.assertEqual(ref(), None)

    def testAnonymousJsFunctionHasNullNameAttribute(self):
        cx = pymonkey.Runtime().new_context()
        obj = cx.new_object()
        cx.init_standard_classes(obj)
        jsfunc = cx.evaluate_script(obj, "(function() {})",
                                    "<string>", 1)
        self.assertEqual(jsfunc.name, None)

    def testJsFunctionHasNameAttribute(self):
        cx = pymonkey.Runtime().new_context()
        obj = cx.new_object()
        cx.init_standard_classes(obj)
        jsfunc = cx.evaluate_script(obj, "(function blarg() {})",
                                    "<string>", 1)
        self.assertEqual(jsfunc.name, "blarg")

    def testJsWrappedPythonFuncHasNameAttribute(self):
        def func(cx, this, args):
            return True

        cx = pymonkey.Runtime().new_context()
        jsfunc = cx.new_function(func, "foo")
        self.assertEqual(jsfunc.name, "foo")

    def testJsWrappedPythonFuncIsGCdAtRuntimeDestruction(self):
        def define(cx, obj):
            def func(cx, this, args):
                return u'func was called'
            jsfunc = cx.new_function(func, func.__name__)
            cx.define_property(obj, func.__name__, jsfunc)
            return weakref.ref(func)
        rt = pymonkey.Runtime()
        cx = rt.new_context()
        obj = cx.new_object()
        cx.init_standard_classes(obj)
        ref = define(cx, obj)
        del rt
        del cx
        del obj
        self.assertEqual(ref(), None)

    def testJsWrappedPythonFuncThrowsExcIfPrivateCleared(self):
        def func(cx, this, args):
            return True

        code = "func()"
        cx = pymonkey.Runtime().new_context()
        obj = cx.new_object()
        cx.init_standard_classes(obj)
        jsfunc = cx.new_function(func, func.__name__)
        cx.define_property(obj, func.__name__, jsfunc)
        cx.clear_object_private(jsfunc)
        self.assertRaises(pymonkey.error,
                          cx.evaluate_script,
                          obj, code, '<string>', 1)
        self.assertEqual(
            self._tostring(cx, self.last_exception.args[0]),
            "Error: Wrapped Python function no longer exists"
            )

    def testJsWrappedPythonFuncPassesContext(self):
        contexts = []

        def func(cx, this, args):
            contexts.append(cx)
            return True

        code = "func()"
        cx = pymonkey.Runtime().new_context()
        obj = cx.new_object()
        cx.init_standard_classes(obj)
        jsfunc = cx.new_function(func, func.__name__)
        self._clearOnTeardown(jsfunc)
        cx.define_property(obj, func.__name__, jsfunc)
        cx.evaluate_script(obj, code, '<string>', 1)
        self.assertEqual(contexts[0], cx)

    def testJsWrappedPythonFuncPassesThisArg(self):
        thisObjs = []

        def func(cx, this, args):
            thisObjs.append(this)
            return True

        code = "func()"
        cx = pymonkey.Runtime().new_context()
        obj = cx.new_object()
        cx.init_standard_classes(obj)
        jsfunc = cx.new_function(func, func.__name__)
        self._clearOnTeardown(jsfunc)
        cx.define_property(obj, func.__name__, jsfunc)
        cx.evaluate_script(obj, code, '<string>', 1)
        self.assertEqual(thisObjs[0], obj)

    def testJsWrappedPythonFuncPassesFuncArgs(self):
        funcArgs = []

        def func(cx, this, args):
            funcArgs.append(args)
            return True

        cx = pymonkey.Runtime().new_context()
        obj = cx.new_object()
        cx.init_standard_classes(obj)
        jsfunc = cx.new_function(func, func.__name__)
        self._clearOnTeardown(jsfunc)

        cx.define_property(obj, func.__name__, jsfunc)

        cx.evaluate_script(obj, "func()", '<string>', 1)
        self.assertEqual(len(funcArgs[0]), 0)
        self.assertTrue(isinstance(funcArgs[0], tuple))

        cx.evaluate_script(obj, "func(1, 'foo')", '<string>', 1)
        self.assertEqual(len(funcArgs[1]), 2)
        self.assertEqual(funcArgs[1][0], 1)
        self.assertEqual(funcArgs[1][1], u'foo')

    def testJsWrappedPythonFunctionReturnsUnicodeWithEmbeddedNULs(self):
        def hai2u(cx, this, args):
            return args[0] + u"o hai"
        self.assertEqual(self._evalJsWrappedPyFunc(hai2u,
                                                   'hai2u("blah\x00 ")'),
                         u"blah\x00 o hai")

    def testJsWrappedPythonFunctionReturnsString(self):
        def hai2u(cx, this, args):
            return "o hai"
        self.assertEqual(self._evalJsWrappedPyFunc(hai2u, 'hai2u()'),
                         "o hai")

    def testJsWrappedPythonFunctionReturnsUnicode(self):
        def hai2u(cx, this, args):
            return u"o hai\u2026"
        self.assertEqual(self._evalJsWrappedPyFunc(hai2u, 'hai2u()'),
                         u"o hai\u2026")

    def testJsWrappedPythonFunctionThrowsJsException(self):
        def hai2u(cx, this, args):
            raise pymonkey.error(u"blarg")
        self.assertRaises(pymonkey.error,
                          self._evalJsWrappedPyFunc,
                          hai2u, 'hai2u()')
        self.assertEqual(self.last_exception.args[0], u"blarg")

    def testJsWrappedPythonFunctionThrowsPyException(self):
        thecx = []
        def hai2u(cx, this, args):
            thecx.append(cx)
            raise Exception("hello")
        self.assertRaises(pymonkey.error,
                          self._evalJsWrappedPyFunc,
                          hai2u, 'hai2u()')
        exc = thecx[0].get_object_private(self.last_exception.args[0])
        self.assertEqual(exc.args[0], "hello")

    def testJsWrappedPythonFunctionReturnsNone(self):
        def hai2u(cx, this, args):
            pass
        self.assertEqual(self._evalJsWrappedPyFunc(hai2u, 'hai2u()'),
                         None)

    def testJsWrappedPythonFunctionReturnsTrue(self):
        def hai2u(cx, this, args):
            return True
        self.assertEqual(self._evalJsWrappedPyFunc(hai2u, 'hai2u()'),
                         True)

    def testJsWrappedPythonFunctionReturnsFalse(self):
        def hai2u(cx, this, args):
            return False
        self.assertEqual(self._evalJsWrappedPyFunc(hai2u, 'hai2u()'),
                         False)

    def testJsWrappedPythonFunctionReturnsSmallInt(self):
        def hai2u(cx, this, args):
            return 5
        self.assertEqual(self._evalJsWrappedPyFunc(hai2u, 'hai2u()'),
                         5)

    def testJsWrappedPythonFunctionReturnsFloat(self):
        def hai2u(cx, this, args):
            return 5.1
        self.assertEqual(self._evalJsWrappedPyFunc(hai2u, 'hai2u()'),
                         5.1)

    def testJsWrappedPythonFunctionReturnsNegativeInt(self):
        def hai2u(cx, this, args):
            return -5
        self.assertEqual(self._evalJsWrappedPyFunc(hai2u, 'hai2u()'),
                         -5)

    def testJsWrappedPythonFunctionReturnsBigInt(self):
        def hai2u(cx, this, args):
            return 2147483647
        self.assertEqual(self._evalJsWrappedPyFunc(hai2u, 'hai2u()'),
                         2147483647)

    def testHasPropertyWorks(self):
        cx = pymonkey.Runtime().new_context()
        obj = cx.new_object()
        cx.init_standard_classes(obj)
        foo = cx.new_object()
        cx.define_property(obj, u"foo\u2026", foo)
        self.assertTrue(cx.has_property(obj, u"foo\u2026"))
        self.assertFalse(cx.has_property(obj, "bar"))

    def testDefinePropertyWorksWithUnicodePropertyNames(self):
        cx = pymonkey.Runtime().new_context()
        obj = cx.new_object()
        cx.init_standard_classes(obj)
        foo = cx.new_object()
        cx.define_property(obj, u"foo\u2026", foo)
        self.assertEqual(
            cx.get_property(obj, u"foo\u2026"),
            foo
            )

    def testDefinePropertyWorksWithObject(self):
        cx = pymonkey.Runtime().new_context()
        obj = cx.new_object()
        cx.init_standard_classes(obj)
        foo = cx.new_object()
        cx.define_property(obj, "foo", foo)
        self.assertEqual(
            cx.evaluate_script(obj, 'foo', '<string>', 1),
            foo
            )

    def testDefinePropertyWorksWithString(self):
        cx = pymonkey.Runtime().new_context()
        obj = cx.new_object()
        cx.init_standard_classes(obj)
        foo = cx.new_object()
        cx.define_property(obj, "foo", u"hello")
        self.assertEqual(
            cx.evaluate_script(obj, 'foo', '<string>', 1),
            u"hello"
            )

    def testObjectIsIdentityPreserving(self):
        cx = pymonkey.Runtime().new_context()
        obj = cx.new_object()
        cx.init_standard_classes(obj)
        cx.evaluate_script(obj, 'var foo = {bar: 1}', '<string>', 1)
        self.assertTrue(isinstance(cx.get_property(obj, u"foo"),
                                   pymonkey.Object))
        self.assertTrue(cx.get_property(obj, u"foo") is
                        cx.get_property(obj, "foo"))

    def testObjectGetattrThrowsException(self):
        cx = pymonkey.Runtime().new_context()
        obj = cx.new_object()
        cx.init_standard_classes(obj)
        result = cx.evaluate_script(obj, '({get foo() { throw "blah"; }})',
                                    '<string>', 1)
        self.assertRaises(pymonkey.error,
                          cx.get_property,
                          result,
                          u"foo")
        self.assertEqual(self.last_exception.args[0], u"blah")

    def testInfiniteRecursionRaisesError(self):
        cx = pymonkey.Runtime().new_context()
        obj = cx.new_object()
        cx.init_standard_classes(obj)
        self.assertRaises(
            pymonkey.error,
            cx.evaluate_script,
            obj, '(function foo() { foo(); })();', '<string>', 1
            )
        self.assertEqual(
            self._tostring(cx, self.last_exception.args[0]),
            "InternalError: too much recursion"
            )

    def testObjectGetattrWorks(self):
        cx = pymonkey.Runtime().new_context()
        obj = cx.new_object()
        cx.init_standard_classes(obj)
        cx.evaluate_script(obj, 'var boop = 5', '<string>', 1)
        cx.evaluate_script(obj, 'this["blarg\u2026"] = 5', '<string>', 1)
        self.assertEqual(cx.get_property(obj, u"beans"),
                         pymonkey.undefined)
        self.assertEqual(cx.get_property(obj, u"blarg\u2026"), 5)
        self.assertEqual(cx.get_property(obj, u"boop"), 5)

    def testContextIsInstance(self):
        cx = pymonkey.Runtime().new_context()
        self.assertTrue(isinstance(cx, pymonkey.Context))

    def testContextTypeCannotBeInstantiated(self):
        self.assertRaises(TypeError, pymonkey.Context)

    def testObjectIsInstance(self):
        obj = pymonkey.Runtime().new_context().new_object()
        self.assertTrue(isinstance(obj, pymonkey.Object))
        self.assertFalse(isinstance(obj, pymonkey.Function))

    def testObjectTypeCannotBeInstantiated(self):
        self.assertRaises(TypeError, pymonkey.Object)

    def testFunctionIsInstance(self):
        def boop():
            pass
        obj = pymonkey.Runtime().new_context().new_function(boop, "boop")
        self.assertTrue(isinstance(obj, pymonkey.Object))
        self.assertTrue(isinstance(obj, pymonkey.Function))

    def testFunctionTypeCannotBeInstantiated(self):
        self.assertRaises(TypeError, pymonkey.Function)

    def testObjectGetRuntimeWorks(self):
        rt = pymonkey.Runtime()
        obj = rt.new_context().new_object()
        self.assertEqual(obj.get_runtime(), rt)

    def testContextGetRuntimeWorks(self):
        rt = pymonkey.Runtime()
        cx = rt.new_context()
        self.assertEqual(cx.get_runtime(), rt)

    def testRuntimesAreWeakReferencable(self):
        rt = pymonkey.Runtime()
        wrt = weakref.ref(rt)
        self.assertEqual(rt, wrt())
        del rt
        self.assertEqual(wrt(), None)

    def testContextsAreWeakReferencable(self):
        rt = pymonkey.Runtime()
        cx = rt.new_context()
        wcx = weakref.ref(cx)
        self.assertEqual(cx, wcx())
        del cx
        self.assertEqual(wcx(), None)

    def testUndefinedCannotBeInstantiated(self):
        self.assertRaises(TypeError, pymonkey.undefined)

    def testEvaluateThrowsException(self):
        cx = pymonkey.Runtime().new_context()
        obj = cx.new_object()
        self.assertRaises(pymonkey.error,
                          cx.evaluate_script,
                          obj, 'hai2u()', '<string>', 1)
        self.assertEqual(self._tostring(cx,
                                        self.last_exception.args[0]),
                         'ReferenceError: hai2u is not defined')

    def testThrowingObjWithBadToStringWorks(self):
        self.assertRaises(
            pymonkey.error,
            self._evaljs,
            "throw {toString: function() { throw 'dujg' }}"
            )
        self.assertEqual(
            self.last_exception.args[1],
            "<string conversion failed>"
            )

    def testEvaluateTakesUnicodeCode(self):
        self.assertEqual(self._evaljs(u"'foo\u2026'"),
                         u"foo\u2026")

    def testEvaluateReturnsUndefined(self):
        retval = self._evaljs("")
        self.assertTrue(retval is pymonkey.undefined)

    def testEvaludateReturnsUnicodeWithEmbeddedNULs(self):
        retval = self._evaljs("'\x00hi'")
        self.assertEqual(retval, u'\x00hi')

    def testEvaluateReturnsSMPUnicode(self):
        # This is 'LINEAR B SYLLABLE B008 A', in the supplementary
        # multilingual plane (SMP).
        retval = self._evaljs("'\uD800\uDC00'")
        self.assertEqual(retval, u'\U00010000')
        self.assertEqual(retval.encode('utf-16'),
                         '\xff\xfe\x00\xd8\x00\xdc')

    def testEvaluateReturnsBMPUnicode(self):
        retval = self._evaljs("'o hai\u2026'")
        self.assertTrue(type(retval) == unicode)
        self.assertEqual(retval, u'o hai\u2026')

    def testEvaluateReturnsObject(self):
        cx = pymonkey.Runtime().new_context()
        obj = cx.new_object()
        cx.init_standard_classes(obj)
        obj = cx.evaluate_script(obj, '({boop: 1})', '<string>', 1)
        self.assertTrue(isinstance(obj, pymonkey.Object))
        self.assertEqual(cx.get_property(obj, u"boop"), 1)

    def testEvaluateReturnsFunction(self):
        cx = pymonkey.Runtime().new_context()
        obj = cx.new_object()
        cx.init_standard_classes(obj)
        obj = cx.evaluate_script(obj, '(function boop() { return 1; })',
                                 '<string>', 1)
        self.assertTrue(isinstance(obj, pymonkey.Function))

    def testJsExceptionStateIsClearedAfterExceptionIsCaught(self):
        cx = pymonkey.Runtime().new_context()
        obj = cx.new_object()
        self.assertRaises(pymonkey.error,
                          cx.evaluate_script,
                          obj, 'blah()', '<string>', 1)
        self.assertEqual(cx.evaluate_script(obj, '5+3', '<string>', 1),
                         8)

    def testCallFunctionRaisesErrorOnBadFuncArgs(self):
        cx = pymonkey.Runtime().new_context()
        obj = cx.new_object()
        obj = cx.evaluate_script(
            obj,
            '(function boop(a, b) { return a+b+this.c; })',
            '<string>', 1
            )
        self.assertRaises(
            NotImplementedError,
            cx.call_function,
            obj, obj, (1, self)
            )

    def _tostring(self, cx, obj):
        return cx.call_function(obj,
                                cx.get_property(obj, u"toString"),
                                ())

    def testCallFunctionRaisesErrorFromJS(self):
        cx = pymonkey.Runtime().new_context()
        obj = cx.new_object()
        obj = cx.evaluate_script(
            obj,
            '(function boop(a, b) { blarg(); })',
            '<string>', 1
            )
        self.assertRaises(pymonkey.error,
                          cx.call_function,
                          obj, obj, (1,))
        self.assertEqual(self._tostring(cx,
                                        self.last_exception.args[0]),
                         'ReferenceError: blarg is not defined')

    def testInitStandardClassesRaisesExcOnRuntimeMismatch(self):
        cx2 = pymonkey.Runtime().new_context()
        cx = pymonkey.Runtime().new_context()
        obj = cx.new_object()
        self.assertRaises(ValueError,
                          cx2.init_standard_classes,
                          obj)
        self.assertEqual(self.last_exception.args[0],
                         'JS runtime mismatch')

    def testCallFunctionWorks(self):
        cx = pymonkey.Runtime().new_context()
        obj = cx.new_object()
        thisArg = cx.new_object()
        cx.define_property(thisArg, "c", 3)
        cx.init_standard_classes(obj)
        obj = cx.evaluate_script(
            obj,
            '(function boop(a, b) { return a+b+this.c; })',
            '<string>', 1
            )
        self.assertEqual(cx.call_function(thisArg, obj, (1,2)), 6)

    def testEvaluateReturnsTrue(self):
        self.assertTrue(self._evaljs('true') is True)

    def testEvaluateReturnsFalse(self):
        self.assertTrue(self._evaljs('false') is False)

    def testEvaluateReturnsNone(self):
        self.assertTrue(self._evaljs('null') is None)

    def testEvaluateReturnsIntegers(self):
        self.assertEqual(self._evaljs('1+3'), 4)

    def testEvaluateReturnsNegativeIntegers(self):
        self.assertEqual(self._evaljs('-5'), -5)

    def testEvaluateReturnsBigIntegers(self):
        self.assertEqual(self._evaljs('2147483647*2'),
                         2147483647*2)

    def testEvaluateReturnsFloats(self):
        self.assertEqual(self._evaljs('1.1+3'), 4.1)

if __name__ == '__main__':
    unittest.main()
