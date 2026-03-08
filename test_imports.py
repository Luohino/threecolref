
print("Testing imports...")
try:
    import threecolref.constants
    print("Constants OK")
    import threecolref.logging
    print("Logging OK")
    import threecolref.items
    print("Items OK")
    import threecolref.collaboration.manager
    print("Collaboration Manager OK")
    import threecolref.view
    print("View OK")
    import threecolref.__main__
    print("Main OK")
    print("All imports SUCCESSFUL")
except Exception as e:
    import traceback
    traceback.print_exc()
    exit(1)
