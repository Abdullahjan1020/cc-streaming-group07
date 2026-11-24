# AKS and Istio Deployment Plan

This milestone provides Kubernetes and Istio manifests but does not create an AKS cluster or
install Istio. Docker Compose remains the local runtime.

## Version Selection

Target:

- Istio 1.32.x
- AKS Kubernetes 1.36 or 1.37
- Azure Linux 3 node images

Record exact patch versions before deployment:

```powershell
az aks get-versions --location <region> --output table
istioctl version
kubectl version
```

Do not select a patch version until it is available in the target Azure region and
`istioctl x precheck` succeeds against the AKS cluster.

## Istio Installation

No Istio IngressGateway is required.

```powershell
istioctl install `
  --set profile=minimal `
  --set values.pilot.resources.requests.cpu=100m `
  --set values.pilot.resources.requests.memory=128Mi `
  --set values.pilot.resources.limits.cpu=500m `
  --set values.pilot.resources.limits.memory=512Mi `
  -y
```

Validate the installation:

```powershell
kubectl get pods -n istio-system
istioctl proxy-status
istioctl analyze
```

## Local Validation

Render the Kubernetes base:

```powershell
kubectl kustomize kubernetes/base
```

Render the AKS overlay:

```powershell
kubectl kustomize kubernetes/overlays/aks
```

Validate Kubernetes resources without connecting to a cluster:

```powershell
kubectl apply --dry-run=client --validate=false -k kubernetes/base
kubectl apply --dry-run=client --validate=false -k kubernetes/overlays/aks
```

Render Istio resources:

```powershell
kubectl kustomize istio
```

## AKS Deployment

Use a one-time ACR image patch in the AKS overlay. Replace the placeholder ACR and tag values
in `kubernetes/overlays/aks/kustomization.yaml` before deployment.

Example deployment commands are intentionally not automated:

```powershell
kubectl apply -k kubernetes/overlays/aks
kubectl apply -k istio
kubectl get pods -n group07
```

The `secrets.example.yaml` file contains placeholders only. Create an actual Secret outside Git
or through a secret-management process before deployment.

## APISIX

Docker Compose continues to use `apisix/config.yaml` and `apisix/routes/*.json`.

Kubernetes uses:

- `kubernetes/base/apisix/configmap.yaml`
- `kubernetes/base/apisix/routes-configmap.yaml`
- Kubernetes Service DNS upstream names

The public LoadBalancer exposes only port 8000. The APISIX Admin API remains exposed only through
the internal ClusterIP on port 9180.

The bootstrap Job uses native Istio sidecar injection. The manifest should be verified in a real
cluster because `nativeSidecar` support depends on the exact Istio patch.

The bootstrap Job uses native Istio sidecar support by default. Native sidecars are the preferred
way to allow the Job main container to finish while the injected sidecar does not prevent Job
completion. The exact behavior must be verified with the selected Istio 1.32 patch and Kubernetes
1.36 or 1.37.

The optional fallback must be enabled explicitly after native-sidecar verification is no longer
desired or only as a compatibility fallback:

```sh
curl --fail --show-error --silent --request POST \
  http://127.0.0.1:15000/quitquitquit >/dev/null
```

If native sidecar support is unavailable in the selected Istio patch, use this fallback or
run the bootstrap as a non-injected Job for Stage 1.
