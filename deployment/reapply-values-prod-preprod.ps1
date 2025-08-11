./process-template.ps1 -TemplateFile respondr-k8s-unified-template.yaml -OutputFile respondr-k8s-generated-prod.yaml -ValuesFile values.yaml
kubectl apply -f respondr-k8s-generated-prod.yaml -n respondr
kubectl rollout status deployment/respondr-deployment -n respondr --timeout=300s

./process-template.ps1 -TemplateFile respondr-k8s-unified-template.yaml -OutputFile respondr-k8s-generated-preprod.yaml -ValuesFile values-preprod.yaml
kubectl apply -f respondr-k8s-generated-preprod.yaml -n respondr-preprod
kubectl rollout status deployment/respondr-deployment -n respondr-preprod --timeout=300s
