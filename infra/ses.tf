data "aws_iam_policy_document" "ses_to_inbox" {
  statement {
    sid       = "AllowSesReceiptDelivery"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.inbox.arn}/*"]
    principals {
      type        = "Service"
      identifiers = ["ses.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:Referer"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

resource "aws_s3_bucket_policy" "inbox" {
  bucket = aws_s3_bucket.inbox.id
  policy = data.aws_iam_policy_document.ses_to_inbox.json
}
