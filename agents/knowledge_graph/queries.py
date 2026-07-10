def get_failing_assets(session, zone_id: str):
    query = """
    MATCH (z:Zone {id: $zone_id})<-[:LOCATED_IN]-(a:Asset)<-[:INSPECTS]-(i:Inspection {result: "FAIL"})
    RETURN a, i ORDER BY i.date DESC
    """
    result = session.run(query, zone_id=zone_id)
    return [record.data() for record in result]

def get_historical_rfis(session, asset_type: str):
    query = """
    MATCH (r:RFI)-[:ABOUT]->(a:Asset {type: $asset_type})
    WHERE r.status = "resolved"
    RETURN r, a ORDER BY r.created_date DESC LIMIT 20
    """
    result = session.run(query, asset_type=asset_type)
    return [record.data() for record in result]

def get_current_approved_drawing(session, zone_id: str):
    query = """
    MATCH (z:Zone {id: $zone_id})<-[:BELONGS_TO]-(p:Project)<-[:BELONGS_TO]-(d:Drawing)
    WHERE NOT (d)-[:SUPERSEDES]->()
    RETURN d ORDER BY d.approved_date DESC
    """
    result = session.run(query, zone_id=zone_id)
    return [record.data() for record in result]

def get_zone_risk_score(session, zone_id: str):
    query = """
    MATCH (z:Zone {id: $zone_id})<-[:LOCATED_IN]-(a:Asset)<-[:INSPECTS]-(i:Inspection)
    WHERE i.date > datetime() - duration('P30D')
    RETURN z.id as zone_id, 
           count(CASE WHEN i.result = 'FAIL' THEN 1 END) as failures,
           count(i) as total,
           toFloat(count(CASE WHEN i.result = 'FAIL' THEN 1 END)) / count(i) as risk_score
    """
    result = session.run(query, zone_id=zone_id)
    data = [record.data() for record in result]
    if data:
        return data[0]
    return {"zone_id": zone_id, "failures": 0, "total": 0, "risk_score": 0.0}
