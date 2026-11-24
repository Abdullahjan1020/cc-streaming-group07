$ErrorActionPreference = "Stop"

Write-Host "Rendering Kubernetes base..."
kubectl kustomize kubernetes/base | Out-Null

Write-Host "Rendering AKS overlay..."
kubectl kustomize kubernetes/overlays/aks | Out-Null

Write-Host "Rendering Istio resources..."
kubectl kustomize istio | Out-Null

Write-Host "[PASS] Kubernetes and Istio manifests render successfully"
