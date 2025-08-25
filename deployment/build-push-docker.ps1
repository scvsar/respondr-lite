# Log in (use your Docker Hub username and PAT/password)
docker login

# Pick a tag. Use your date-based tag to match Bicep:
$TAG = "2025-08-25"
$IMAGE = "randytreit/respondr:$TAG"

Push-Location -Path ..

# Make sure we build a Linux image (ACA runs Linux). 
# Add --platform to avoid accidental windows/arm images on dev machines.
docker build --platform linux/amd64 -t $IMAGE -f .\Dockerfile .

# (Optional) also tag "latest" so you have a stable tag if you want it
docker tag $IMAGE randytreit/respondr:latest

# Push both tags (or just the dated one if you prefer)
docker push $IMAGE
docker push randytreit/respondr:latest

Pop-Location