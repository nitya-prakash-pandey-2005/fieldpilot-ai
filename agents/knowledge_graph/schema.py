def setup_constraints(session):
    """
    Initializes the required constraints for the ASK THE WALL ontology.
    """
    constraints = [
        "CREATE CONSTRAINT project_id IF NOT EXISTS FOR (p:Project) REQUIRE p.id IS UNIQUE",
        "CREATE CONSTRAINT zone_id IF NOT EXISTS FOR (z:Zone) REQUIRE z.id IS UNIQUE",
        "CREATE CONSTRAINT asset_id IF NOT EXISTS FOR (a:Asset) REQUIRE a.id IS UNIQUE",
        "CREATE CONSTRAINT drawing_id IF NOT EXISTS FOR (d:Drawing) REQUIRE d.id IS UNIQUE",
        "CREATE CONSTRAINT spec_id IF NOT EXISTS FOR (s:Specification) REQUIRE s.id IS UNIQUE",
        "CREATE CONSTRAINT rfi_id IF NOT EXISTS FOR (r:RFI) REQUIRE r.id IS UNIQUE",
        "CREATE CONSTRAINT inspection_id IF NOT EXISTS FOR (i:Inspection) REQUIRE i.id IS UNIQUE",
        "CREATE CONSTRAINT worker_id IF NOT EXISTS FOR (w:Worker) REQUIRE w.id IS UNIQUE",
        "CREATE CONSTRAINT engineer_id IF NOT EXISTS FOR (e:Engineer) REQUIRE e.id IS UNIQUE"
    ]
    
    for query in constraints:
        try:
            session.run(query)
        except Exception as e:
            print(f"Warning setting up constraint: {e}")
