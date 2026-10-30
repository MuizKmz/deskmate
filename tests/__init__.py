import logging

# Keep expected warnings (like "settings file was unreadable") out of the test output.
logging.getLogger("deskmate").addHandler(logging.NullHandler())
logging.getLogger("deskmate").propagate = False
