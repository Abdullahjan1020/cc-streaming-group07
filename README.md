# Cloud Computing Group 07

Group 07 semester project: a Python 3.12 FastAPI microservices platform for a
cloud-native service mesh, API gateway routing, distributed infrastructure,
monitoring preparation, and controlled resilience experiments.

Repository: `Abdullahjan1020/cc-streaming-group07`

## Current Implementation Status

Locally runtime-tested components:

- Four independent FastAPI microservices
- MongoDB as the only primary database
- Redis caching and session storage
- Docker Compose local infrastructure
- APISIX gateway routing and route bootstrap
- Hardened local Docker images for all four application services
- Unit tests for the four services

Statically validated Kubernetes and Istio configuration:

- Kubernetes base manifests and AKS Kustomize overlay
- Istio PeerAuthentication, DestinationRule, and VirtualService manifests
- Kubernetes manifests
- AKS overlay placeholders
- Istio sidecars and mTLS
- NetworkPolicies
- Istio native-sidecar bootstrap lifecycle
- APISIX-to-Kubernetes routing

Not yet implemented or runtime-validated:

- SkyWalking configuration and deployment
- Prometheus configuration and deployment
- Grafana dashboards
- A live AKS cluster
- ACR creation and image pushing
- Canary releases
- Controlled fault-injection experiments

## Architecture

```text
External client
  -> APISIX LoadBalancer/Gateway
  -> FastAPI application Services
  -> MongoDB / Redis

Docker Compose local environment:
  User, Product, Order, Notification
  -> MongoDB
  -> Redis

AKS target environment:
  APISIX LoadBalancer
  -> Kubernetes Services
  -> Istio/Envoy sidecars
  -> FastAPI application Pods

Order Service
  -> Product Service
  -> Notification Service
```

APISIX remains the external API gateway. The Kubernetes design does not add an
Istio IngressGateway. Istio manifests are intended for the application mesh;
MongoDB, Redis, and etcd are designed to run outside sidecar injection.

## Technology Stack

- Python 3.12
- FastAPI
- PyMongo Async through `AsyncMongoClient`
- Redis
- MongoDB
- Apache APISIX
- etcd
- Istio and Envoy
- Docker and Docker Compose
- Kubernetes and Azure Kubernetes Service
- Kustomize
- Pytest and HTTPX
- Optional/future: SkyWalking, Prometheus, and Grafana

MongoDB is the only primary database. PostgreSQL is not used. Motor is not used.

## Microservices

| Service | Port | MongoDB database | Responsibility |
|---|---:|---|---|
| User | 8001 | `user_db` | Registration, login, and user profile |
| Product | 8002 | `product_db` | Product creation, listing, retrieval, update, and deletion |
| Order | 8003 | `order_db` | Order creation/retrieval, status management, and product availability validation |
| Notification | 8004 | `notification_db` | Notification creation and order-related notification history |

### User Service

- `POST /users/register`
- `POST /auth/login`
- `GET /users/me`
- `GET /health`

### Product Service

- `POST /products`
- `GET /products`
- `GET /products/{product_id}`
- `PATCH /products/{product_id}`
- `DELETE /products/{product_id}`
- `GET /health`

Product list and item responses use Redis caching where configured.

### Order Service

- `POST /orders`
- `GET /orders/{order_id}`
- `GET /users/{user_id}/orders`
- `PATCH /orders/{order_id}/status`
- `GET /health`

Order creation validates product availability through the Product Service.

### Notification Service

- `POST /notifications`
- `GET /notifications`
- `GET /health`

## Data and Cache

MongoDB and Redis are used by Docker Compose and Kubernetes manifests:

- MongoDB: `mongodb://mongodb:27017` locally
- Redis: `redis://redis:6379/0` locally
- MongoDB databases: `user_db`, `product_db`, `order_db`, `notification_db`
- Redis cache and user session storage
- Named Docker volumes preserve local MongoDB and Redis data

PostgreSQL and Motor are not used.

## Docker Compose Local Environment

Copy the environment template:

```powershell
Copy-Item .env.example .env
```

Start the complete local stack:

```powershell
docker compose up -d --build
```

Start only data dependencies:

```powershell
docker compose up -d mongodb redis
```

Check container status:

```powershell
docker compose ps
```

Check direct service health:

```powershell
Invoke-RestMethod http://127.0.0.1:8001/health
Invoke-RestMethod http://127.0.0.1:8002/health
Invoke-RestMethod http://127.0.0.1:8003/health
Invoke-RestMethod http://127.0.0.1:8004/health
```

Stop containers while preserving named-volume data:

```powershell
docker compose down
```

Do not use `docker compose down -v` unless local database data should be removed.

## APISIX Gateway

Local APISIX and etcd are available through Docker Compose.

- Public gateway: `127.0.0.1:8000`
- Internal APISIX Admin API: `apisix:9180`
- APISIX gateway listener: container port `9080`
- APISIX configuration: `apisix/config.yaml`
- Route definitions: `apisix/routes/*.json`
- etcd image: `quay.io/coreos/etcd:v3.5.17`

The Docker Compose bootstrap registers these routes:

| Gateway route | Local upstream |
|---|---|
| `/gateway/health` | `user-service:8001/health` |
| `/api/users/*` | `user-service:8001` |
| `/api/auth/*` | `user-service:8001` |
| `/api/products/*` | `product-service:8002` |
| `/api/orders/*` | `order-service:8003` |
| `/api/users/*/orders` | `order-service:8003` |
| `/api/notifications/*` | `notification-service:8004` |

Gateway test script:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\test-apisix.ps1
```

The Kubernetes manifests contain separate APISIX Kubernetes route
configuration with Kubernetes Service DNS upstreams. Docker Compose route files
remain unchanged.

### Kubernetes Rate Limiting and Circuit Breaker

The Kubernetes orders route in
`kubernetes/base/apisix/routes-configmap.yaml` keeps its existing
`proxy-rewrite` configuration and adds these APISIX 3.12 plugins:

- `limit-count` allows 60 requests per 60-second fixed window per source IP and
  returns HTTP `429` when the quota is exceeded. It uses local counters on each
  APISIX instance; clients sharing a source IP share a quota. The current APISIX
  Deployment has one replica, so this is a per-instance limit. If the gateway
  is scaled out, each replica will maintain its own counter.
- `api-breaker` considers upstream responses `500`, `502`, `503`, or `504`
  unhealthy. After 3 failures, it returns HTTP `503` while the circuit is open.
  The breaker backs off up to 30 seconds and can recover after 2 upstream
  responses with status `200`, `201`, `202`, or `204`.

The exact plugin configuration is:

```json
{
  "limit-count": {
    "count": 60,
    "time_window": 60,
    "key_type": "var",
    "key": "remote_addr",
    "policy": "local",
    "rejected_code": 429,
    "show_limit_quota_header": true
  },
  "api-breaker": {
    "break_response_code": 503,
    "max_breaker_sec": 30,
    "unhealthy": {
      "http_statuses": [500, 502, 503, 504],
      "failures": 3
    },
    "healthy": {
      "http_statuses": [200, 201, 202, 204],
      "successes": 2
    }
  }
}
```

After changing the Kubernetes route ConfigMap, delete and recreate the
bootstrap Job to upload the routes to the APISIX Admin API:

```powershell
kubectl delete job apisix-config -n group07 --ignore-not-found
kubectl apply -k kubernetes/base
kubectl wait --for=condition=complete job/apisix-config -n group07 --timeout=120s
kubectl logs job/apisix-config -n group07
```

The logs should end with `APISIX routes configured`. To inspect the registered
orders route, start this port-forward in one terminal:

```powershell
kubectl port-forward -n group07 svc/apisix-admin 9180:9180
```

In another PowerShell terminal, read the key from the Kubernetes Secret into a
variable and request the route. The key is sent in a header and is not printed:

```powershell
$encodedKey = kubectl get secret application-secrets -n group07 -o jsonpath='{.data.apisix-admin-key}'
$adminKey = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($encodedKey))
Invoke-RestMethod -Uri http://127.0.0.1:9180/apisix/admin/routes/orders -Headers @{ "X-API-KEY" = $adminKey } | ConvertTo-Json -Depth 20
Remove-Variable adminKey, encodedKey
```

The returned route should include both `limit-count` and `api-breaker` under
`plugins`. Normal orders requests continue to the order service; requests over
the configured per-IP quota should receive HTTP `429` with rate-limit quota
headers. After the configured upstream failures, requests while the circuit is
open should receive HTTP `503`, followed by recovery after healthy upstream
responses. Runtime circuit-breaker testing still requires an isolated failure
test; do not induce upstream failures on a live environment.

These settings apply to the Kubernetes route only. `apisix/routes/orders.json`
is the separate Docker Compose route configuration and remains unchanged.

## Python Testing

Activate the existing virtual environment:

```powershell
.\.venv\Scripts\Activate.ps1
```

Install the project with development dependencies:

```powershell
python -m pip install -e ".[dev]"
```

Run unit tests:

```powershell
python -m pytest tests/unit -v
```

Check dependencies:

```powershell
python -m pip check
```

## Container Images

All four application images have been built and tested locally as version
`v1.0.0`:

```text
group07/user-service:v1.0.0
group07/product-service:v1.0.0
group07/order-service:v1.0.0
group07/notification-service:v1.0.0
```

Build each image individually:

```powershell
docker build -t group07/user-service:v1.0.0 ./services/user-service
docker build -t group07/product-service:v1.0.0 ./services/product-service
docker build -t group07/order-service:v1.0.0 ./services/order-service
docker build -t group07/notification-service:v1.0.0 ./services/notification-service
```

The service Dockerfiles:

- Use Python `3.12-slim`
- Install dependencies before changing users
- Run as UID/GID `10001`
- Set `PYTHONDONTWRITEBYTECODE=1`
- Set `PYTHONUNBUFFERED=1`
- Include service-specific `.dockerignore` files
- Preserve ports `8001` through `8004`

No image has been pushed to a registry.

## Kubernetes and AKS

Kubernetes manifests are located under [kubernetes/base/](/C:/Users/user/Desktop/5th%20Sem/Cloud%20Computing/cc-streaming-group07/kubernetes/base)
and [kubernetes/overlays/aks/](/C:/Users/user/Desktop/5th%20Sem/Cloud%20Computing/cc-streaming-group07/kubernetes/overlays/aks).

The base includes:

- Namespace and service accounts
- Four application Deployments and Services
- MongoDB StatefulSet, Service, and PVC
- Redis Deployment, Service, and 1 GiB PVC
- etcd StatefulSet, Service, and PVC
- APISIX Deployment, public LoadBalancer, internal Admin Service, and bootstrap Job
- NetworkPolicies
- Example Secret template

The AKS overlay provides image placeholders and AKS resource patches:

```text
REPLACE_WITH_ACR/user-service:REPLACE_WITH_IMAGE_TAG
REPLACE_WITH_ACR/product-service:REPLACE_WITH_IMAGE_TAG
REPLACE_WITH_ACR/order-service:REPLACE_WITH_IMAGE_TAG
REPLACE_WITH_ACR/notification-service:REPLACE_WITH_IMAGE_TAG
```

These placeholders must be replaced with an approved ACR repository and immutable
release tag before deployment. No ACR name or Azure credential is present in
the repository.

Render manifests:

```powershell
kubectl kustomize kubernetes/base
kubectl kustomize kubernetes/overlays/aks
```

Validate Kubernetes and Istio files when local tools are available:

```powershell
kubectl kustomize istio
istioctl validate -f istio/routing/destination-rules.yaml `
  -f istio/routing/virtual-services.yaml `
  -f istio/resilience/peer-authentication.yaml
```

The Kubernetes base and AKS overlay have passed static Kustomize rendering.
They have not been deployed or runtime-tested against AKS.

## Istio and Envoy

Istio manifests under [istio/](/C:/Users/user/Desktop/5th%20Sem/Cloud%20Computing/cc-streaming-group07/istio)
define:

- PeerAuthentication for APISIX workload ports
- STRICT mTLS for the four application workloads
- DISABLE mTLS on APISIX public workload port `9080`
- STRICT mTLS on APISIX Admin workload port `9180`
- ISTIO_MUTUAL DestinationRules for application services
- ISTIO_MUTUAL bootstrap-to-APISIX Admin routing
- Internal VirtualServices for the application Services
- Connection pools and outlier detection

MongoDB, Redis, and etcd are configured outside sidecar injection.

No live AKS cluster has been used, so sidecar injection, mTLS, NetworkPolicy,
bootstrap Job lifecycle, and APISIX-to-Service traffic remain runtime-unverified.

The implementation plan currently targets Istio `1.32.x` and AKS Kubernetes
`1.36` or `1.37`, subject to exact patch versions and Azure region availability.
Exact patch versions must be verified before installation.

## ACR and AKS Prerequisites

Before deployment:

1. Provision an AKS cluster in an available Azure region.
2. Verify Istio 1.32 compatibility with the selected AKS patch.
3. Create or select an ACR instance.
4. Configure AKS-to-ACR image pull access.
5. Replace Kustomize image placeholders with concrete ACR repositories and tags.
6. Create real Kubernetes Secrets outside Git.
7. Verify the target StorageClass for MongoDB, Redis, and etcd PVCs.
8. Install Istio with its minimal profile.
9. Apply namespace, workloads, NetworkPolicies, and Istio resources in stages.

No AKS cluster, ACR, Azure credential, or cloud resource is included or assumed.

## Monitoring Status

SkyWalking, Prometheus, and Grafana directories exist, but this repository
currently contains only placeholders in those areas:

- `skywalking/`
- `monitoring/prometheus/`
- `monitoring/grafana/`

No SkyWalking OAP, tracing agent, Prometheus configuration, Grafana dashboard,
or runtime monitoring stack has been implemented or validated.

## Repository Structure

```text
services/
  user-service/
  product-service/
  order-service/
  notification-service/
  shared/
infrastructure/
kubernetes/
  base/
  overlays/
apisix/
  routes/
  plugins/
istio/
  gateway/
  routing/
  resilience/
  fault-injection/
skywalking/
monitoring/
  prometheus/
  grafana/
scripts/
tests/
docs/
presentation/
```

## Security and Repository Hygiene

- `.env` and `.env.*` are ignored except `.env.example`.
- `.venv` and Python caches are ignored.
- Coverage, build output, logs, database data directories, and generated artifacts are ignored.
- The checked-in Secret template contains placeholders only.
- Real JWT and APISIX Admin keys must be created outside Git.
- Do not commit `.env`, private keys, certificates, passwords, tokens, or Kubernetes Secrets.

## Current Limitations and Remaining Work

- SkyWalking, Prometheus, and Grafana are not implemented.
- Istio mTLS and NetworkPolicies are manifest-only.
- AKS deployment and runtime behavior are untested.
- APISIX Kubernetes routes and bootstrap lifecycle require live-cluster validation.
- Native Istio sidecar Job behavior must be verified with the selected patch.
- Canary releases and fault-injection experiments remain for later milestones.
- Technical report and presentation deliverables may require completion.
- ACR repositories and immutable release tags must replace placeholders.
- MongoDB and Redis persistence are represented in Kubernetes manifests but require cluster StorageClass validation.
