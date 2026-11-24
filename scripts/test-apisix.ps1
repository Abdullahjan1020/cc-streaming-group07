$ErrorActionPreference = "Stop"

function Test-JsonResponse {
    param(
        [string]$Name,
        [string]$Url
    )

    $response = Invoke-RestMethod -Method Get -Uri $Url
    Write-Host "[PASS] $Name $Url"
    return $response
}

Test-JsonResponse "Gateway health" "http://127.0.0.1:8000/gateway/health" | Out-Null
Test-JsonResponse "User direct health" "http://127.0.0.1:8001/health" | Out-Null
Test-JsonResponse "Product gateway route" "http://127.0.0.1:8000/api/products" | Out-Null
Test-JsonResponse "Order direct health" "http://127.0.0.1:8003/health" | Out-Null
Test-JsonResponse "Notification direct health" "http://127.0.0.1:8004/health" | Out-Null
