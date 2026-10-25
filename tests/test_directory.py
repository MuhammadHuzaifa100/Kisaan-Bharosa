def test_get_official_products(client):
    response = client.get("/api/directory/products")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    assert "brand_name" in data[0]
    assert "official_mrp_pkr" in data[0]

def test_filter_official_products_by_category(client):
    response = client.get("/api/directory/products?category=Urea")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    for item in data:
        assert "urea" in item["category"].lower()

def test_analytics_summary(client):
    response = client.get("/api/analytics/summary")
    assert response.status_code == 200
    data = response.json()
    assert "total_scans" in data
    assert "authentic_count" in data
    assert "counterfeit_count" in data
    assert "total_reports" in data
    assert "authenticity_rate" in data

def test_health_check(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
