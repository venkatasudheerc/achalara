"""Tests for client endpoints"""


class TestClientEndpoints:
    """Test client API endpoints"""

    def test_list_clients_empty(self, client):
        """GET /clients/ returns empty list when no clients exist"""
        response = client.get("/api/v1/clients/")
        assert response.status_code == 200
        assert response.json() == []

    def test_list_clients_populated(self, client):
        """GET /clients/ returns all created clients"""
        client.post("/api/v1/clients/", json={"name": "Alpha Fund", "email": "alpha@example.com"})
        client.post("/api/v1/clients/", json={"name": "Beta Fund", "email": "beta@example.com"})

        response = client.get("/api/v1/clients/")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        emails = {c["email"] for c in data}
        assert emails == {"alpha@example.com", "beta@example.com"}

    def test_list_clients_pagination(self, client):
        """GET /clients/?skip=1&limit=1 paginates correctly"""
        client.post("/api/v1/clients/", json={"name": "Fund A", "email": "a@example.com"})
        client.post("/api/v1/clients/", json={"name": "Fund B", "email": "b@example.com"})

        response = client.get("/api/v1/clients/", params={"skip": 1, "limit": 1})
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1

    def test_create_client(self, client):
        """Test creating a new client"""
        response = client.post(
            "/api/v1/clients/", json={"name": "Test Fund", "email": "test@example.com"}
        )

        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Test Fund"
        assert data["email"] == "test@example.com"
        assert "id" in data
        assert "created_at" in data

    def test_create_client_duplicate_email(self, client):
        """Test that duplicate emails are rejected"""
        # Create first client
        response1 = client.post(
            "/api/v1/clients/", json={"name": "Fund One", "email": "same@example.com"}
        )
        assert response1.status_code == 201

        # Try to create second client with same email
        response2 = client.post(
            "/api/v1/clients/", json={"name": "Fund Two", "email": "same@example.com"}
        )
        assert response2.status_code == 400

    def test_get_client(self, client):
        """Test retrieving a client"""
        # Create client
        create_response = client.post(
            "/api/v1/clients/",
            json={"name": "Retrieve Test", "email": "retrieve@example.com"},
        )
        client_id = create_response.json()["id"]

        # Retrieve client
        get_response = client.get(f"/api/v1/clients/{client_id}")
        assert get_response.status_code == 200
        data = get_response.json()
        assert data["name"] == "Retrieve Test"
        assert data["email"] == "retrieve@example.com"

    def test_get_nonexistent_client(self, client):
        """Test retrieving a non-existent client"""
        response = client.get("/api/v1/clients/00000000-0000-0000-0000-000000000000")
        assert response.status_code == 404

    def test_client_performance_endpoint(self, client):
        """Test client performance endpoint"""
        # Create client
        create_response = client.post(
            "/api/v1/clients/",
            json={"name": "Performance Test", "email": "perf@example.com"},
        )
        client_id = create_response.json()["id"]

        # Get performance (LevelPerformance shape)
        response = client.get(f"/api/v1/clients/{client_id}/performance")
        assert response.status_code == 200
        data = response.json()
        assert data["level"] == "client"
        assert data["id"] == client_id
        assert "summary" in data
        assert "timeseries" in data

    def test_client_positions_endpoint(self, client):
        """Test client positions endpoint"""
        # Create client
        create_response = client.post(
            "/api/v1/clients/",
            json={"name": "Positions Test", "email": "pos@example.com"},
        )
        client_id = create_response.json()["id"]

        # Get positions
        response = client.get(f"/api/v1/clients/{client_id}/positions")
        assert response.status_code == 200
        data = response.json()
        assert "positions" in data

    def test_client_trades_endpoint(self, client):
        """Test client trades endpoint"""
        # Create client
        create_response = client.post(
            "/api/v1/clients/",
            json={"name": "Trades Test", "email": "trades@example.com"},
        )
        client_id = create_response.json()["id"]

        # Get trades
        response = client.get(f"/api/v1/clients/{client_id}/trades")
        assert response.status_code == 200
        data = response.json()
        assert "trades" in data


class TestClientDetailsCanBeCorrected:
    def _client(self, client, name="Asha Rao", email="asha@example.com"):
        return client.post("/api/v1/clients/", json={"name": name, "email": email}).json()

    def test_name_and_contact_email_are_changed_and_a_field_left_out_is_kept(self, client):
        made = self._client(client)
        url = f"/api/v1/clients/{made['id']}"

        resp = client.patch(url, json={"email": "asha.new@example.com"})
        assert resp.status_code == 200
        assert (resp.json()["name"], resp.json()["email"]) == (
            "Asha Rao",
            "asha.new@example.com",
        )

        resp = client.patch(url, json={"name": "  Asha R. Rao "})
        assert resp.json()["name"] == "Asha R. Rao"
        assert client.get(url).json()["email"] == "asha.new@example.com"

    def test_an_email_another_client_has_is_refused(self, client):
        first = self._client(client)
        self._client(client, "Bina Shah", "bina@example.com")
        resp = client.patch(
            f"/api/v1/clients/{first['id']}", json={"email": "bina@example.com"}
        )
        assert resp.status_code == 400
        assert client.get(f"/api/v1/clients/{first['id']}").json()["email"] == (
            "asha@example.com"
        )

    def test_a_blank_name_a_bad_email_and_an_unknown_client_are_refused(self, client):
        made = self._client(client)
        url = f"/api/v1/clients/{made['id']}"
        assert client.patch(url, json={"name": "   "}).status_code == 422
        assert client.patch(url, json={"email": "not-an-email"}).status_code == 422
        assert client.patch("/api/v1/clients/nobody", json={"name": "X"}).status_code == 404

    def test_a_new_name_reaches_the_login_and_the_sign_in_email_is_left_alone(
        self, client, db
    ):
        from app.models.user import User

        made = self._client(client)
        client.post(
            "/api/v1/auth/invites",
            json={"client_id": made["id"], "email": "asha.signin@example.com"},
        )
        client.patch(
            f"/api/v1/clients/{made['id']}",
            json={"name": "Asha Rao-Shah", "email": "asha.contact@example.com"},
        )
        login = db.query(User).filter(User.client_id == made["id"]).one()
        assert (login.name, login.email) == ("Asha Rao-Shah", "asha.signin@example.com")
