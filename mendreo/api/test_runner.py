from django.test.runner import DiscoverRunner
from unittest.runner import TextTestRunner, TextTestResult
from time import time
import os


class TimedTextTestResult(TextTestResult):

    def __init__(self, *args, **kwargs):
        super(TimedTextTestResult, self).__init__(*args, **kwargs)
        self.clocks = dict()

    def startTest(self, test):
        self.clocks[test] = time()
        super(TextTestResult, self).startTest(test)
        if self.showAll:
            self.stream.write(self.getDescription(test))
            self.stream.write(" ... ")
            self.stream.flush()

    def addSuccess(self, test):
        super(TextTestResult, self).addSuccess(test)
        if self.showAll:
            self.stream.writeln("ok (%.6fs)" % (time() - self.clocks[test]))
        elif self.dots:
            self.stream.write('.')
            self.stream.flush()


class TimedTextTestRunner(TextTestRunner):
    resultclass = TimedTextTestResult


class ProfileTestRunner(DiscoverRunner):
    test_runner = TimedTextTestRunner

    def build_suite(self, test_labels=None, **kwargs):
        suite = super(ProfileTestRunner, self).build_suite(test_labels, **kwargs)

        ci_node_total = int(os.getenv("CI_NODE_TOTAL", 1))
        ci_node_index = int(os.getenv("CI_NODE_INDEX", 0))

        if ci_node_total == 1:
            return suite

        tests = self.test_suite()

        for i, test in enumerate(suite, start=0):
            if i % ci_node_total == ci_node_index:
                tests.addTest(test)

        print("Tests to run: ")
        print(tests)

        return tests
