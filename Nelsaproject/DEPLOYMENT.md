# Deployment Guide for Render

## Generated Secret Key
**IMPORTANT: Copy this secret key and use it when setting environment variables in Render**

```
DJANGO_SECRET_KEY=*e-&nv+0l6na9hl$w_-!u#6o9#z!y0b0*9mil#-wl7vszi#aol
```

---

## Step-by-Step Deployment Instructions

### 1. Push to GitHub (if not already done)
```bash
git add .
git commit -m "Ready for Render deployment"
git push -u origin main
```

### 2. Create Web Service on Render
1. Go to https://render.com and sign in
2. Click **"New +"** → **"Web Service"**
3. Connect your GitHub repository
4. Select your repository and branch (usually `main`)

### 3. Configure Service Settings

#### Basic Settings:
- **Name**: `GARANTI EXPRESS-express` (or your preferred name)
- **Region**: Choose closest to your users (e.g., `Oregon`, `Frankfurt`, `Singapore`)
- **Branch**: `main`
- **Root Directory**: Leave empty or set to `Nelsaproject` if your project structure requires it
- **Runtime**: `Python 3`
- **Build Command**: 
  ```
  pip install -r requirements.txt && python manage.py collectstatic --noinput
  ```
- **Start Command**: 
  ```
  gunicorn Nelsaproject.wsgi:application
  ```

#### ⚠️ ENVIRONMENT VARIABLES - SET THESE MANUALLY:

After creating the service, go to the **Environment** tab and add these variables:

1. **DJANGO_SECRET_KEY**
   - Value: `*e-&nv+0l6na9hl$w_-!u#6o9#z!y0b0*9mil#-wl7vszi#aol`
   - ⚠️ **CRITICAL: Replace with the secret key generated above or generate a new one!**

2. **DJANGO_DEBUG**
   - Value: `False`

3. **ALLOWED_HOSTS**
   - Value: `your-app-name.onrender.com` (Replace with your actual Render app URL)
   - ⚠️ **After deployment, Render will give you a URL. Update this value with your actual URL!**

4. **CSRF_TRUSTED_ORIGINS**
   - Value: `https://your-app-name.onrender.com` (Replace with your actual Render app URL)
   - ⚠️ **Update this after deployment with your actual URL!**

5. **PYTHON_VERSION** (Optional, but recommended)
   - Value: `3.12.0`

### 4. Advanced Settings (Optional)
- **Instance Type**: Free tier is fine for testing. Upgrade to Starter/Standard for production.
- **Auto-Deploy**: Enable to automatically deploy on every push to main branch

### 5. Database (if needed)
If you need a database:
- Go to **"New +"** → **"PostgreSQL"**
- Copy the connection string
- Add as environment variable `DATABASE_URL`
- Update your `settings.py` to use `dj-database-url` if needed

### 6. Deploy
Click **"Create Web Service"** and wait for deployment (5-10 minutes)

### 7. After Deployment
1. **Update ALLOWED_HOSTS**: Once deployed, Render gives you a URL like `https://GARANTI EXPRESS-express.onrender.com`
   - Go to Environment tab
   - Update `ALLOWED_HOSTS` to: `GARANTI EXPRESS-express.onrender.com` (your actual app name)
   - Update `CSRF_TRUSTED_ORIGINS` to: `https://GARANTI EXPRESS-express.onrender.com`

2. **Run Migrations** (if needed):
   - Use Render Shell or add this to build command:
   ```
   pip install -r requirements.txt && python manage.py migrate && python manage.py collectstatic --noinput
   ```

3. **Create Superuser** (if needed):
   - Use Render Shell: `python manage.py createsuperuser`

---

## Important Notes

- ⚠️ **Never commit your secret key to Git!** Use environment variables only.
- ⚠️ **Update ALLOWED_HOSTS and CSRF_TRUSTED_ORIGINS** with your actual Render URL after deployment.
- The free tier on Render spins down after inactivity. First request may be slow.
- Static files are served by WhiteNoise - no additional configuration needed.

---

## Troubleshooting

### Build Fails
- Check Python version matches (3.12.0)
- Ensure all dependencies are in `requirements.txt`
- Check build logs in Render dashboard

### 500 Errors
- Check environment variables are set correctly
- Verify `ALLOWED_HOSTS` includes your Render domain
- Check application logs in Render dashboard

### Static Files Not Loading
- Ensure `collectstatic` runs in build command
- Verify `STATIC_ROOT` is set correctly
- Check WhiteNoise middleware is in `MIDDLEWARE`

---

## Quick Reference Commands

Generate a new secret key:
```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```


