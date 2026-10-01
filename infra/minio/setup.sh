#!/bin/sh
set -eu
# Setup credentials only. Runtime credentials are never used for administration.
mc alias set setup http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null
mc mb --ignore-existing "setup/$S3_BUCKET" >/dev/null
mc version enable "setup/$S3_BUCKET" >/dev/null
cat > /tmp/runtime-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:PutObject", "s3:GetObject", "s3:GetObjectVersion"],
      "Resource": ["arn:aws:s3:::$S3_BUCKET/*"]
    },
    {
      "Effect": "Deny",
      "Action": ["s3:DeleteObject", "s3:DeleteObjectVersion"],
      "Resource": ["arn:aws:s3:::$S3_BUCKET/*"]
    }
  ]
}
EOF
mc admin user add setup "$S3_RUNTIME_ACCESS_KEY" "$S3_RUNTIME_SECRET_KEY" >/dev/null
mc admin policy create setup relay-m0-runtime /tmp/runtime-policy.json >/dev/null
mc admin policy attach setup relay-m0-runtime --user "$S3_RUNTIME_ACCESS_KEY" >/dev/null
printf 'M0 bucket versioning and separate runtime policy configured.\n'
