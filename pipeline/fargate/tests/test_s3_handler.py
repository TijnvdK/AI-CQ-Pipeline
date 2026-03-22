import pytest
from unittest.mock import Mock, patch

# 先 mock boto3.client，再导入模块，避免 import 时真实初始化 AWS client
with patch("boto3.client") as mock_boto3_client:
    mock_s3 = Mock()
    mock_ssm = Mock()
    mock_boto3_client.side_effect = [mock_s3, mock_ssm]

    import src.s3_handler as s3_handler


class TestGetS3BucketName:
    def test_get_s3_bucket_name_success(self):
        with patch.object(s3_handler, "ssm") as mock_ssm:
            mock_ssm.get_parameter.return_value = {
                "Parameter": {
                    "Value": "my-test-bucket"
                }
            }

            result = s3_handler.get_s3_bucket_name()

            assert result == "my-test-bucket"
            mock_ssm.get_parameter.assert_called_once_with(
                Name="/ai-cq-pipeline/s3-bucket-name",
                WithDecryption=False,
            )

    def test_get_s3_bucket_name_failure_logs_and_raises(self):
        with patch.object(s3_handler, "ssm") as mock_ssm, patch.object(s3_handler, "logger") as mock_logger:
            mock_ssm.get_parameter.side_effect = Exception("ssm error")

            with pytest.raises(Exception, match="ssm error"):
                s3_handler.get_s3_bucket_name()

            mock_logger.error.assert_called_once()
            assert "Error retrieving S3 bucket name" in mock_logger.error.call_args[0][0]


class TestSaveHtmlFileToS3:
    def test_save_html_file_to_s3_success(self):
        with patch.object(s3_handler, "s3") as mock_s3, \
             patch.object(s3_handler, "logger") as mock_logger, \
             patch.object(s3_handler, "get_s3_bucket_name", return_value="my-test-bucket"):

            mock_s3.generate_presigned_url.return_value = "https://presigned-url"

            result = s3_handler.save_html_file_to_s3(
                key="path/file.html",
                body="<html>hello</html>",
                content_type="text/html",
            )

            assert result == "https://presigned-url"
            mock_s3.put_object.assert_called_once_with(
                Bucket="my-test-bucket",
                Key="path/file.html",
                Body="<html>hello</html>",
                ContentType="text/html",
            )
            mock_s3.generate_presigned_url.assert_called_once_with(
                ClientMethod="get_object",
                Params={"Bucket": "my-test-bucket", "Key": "path/file.html"},
                ExpiresIn=s3_handler.HTML_URLS_EXPIRE_IN,
            )
            mock_logger.info.assert_called_once_with(
                "Successfully saved file to S3 at path/file.html."
            )

    def test_save_html_file_to_s3_put_object_failure_logs_and_raises(self):
        with patch.object(s3_handler, "s3") as mock_s3, \
             patch.object(s3_handler, "logger") as mock_logger, \
             patch.object(s3_handler, "get_s3_bucket_name", return_value="my-test-bucket"):

            mock_s3.put_object.side_effect = Exception("s3 put error")

            with pytest.raises(Exception, match="s3 put error"):
                s3_handler.save_html_file_to_s3(
                    key="path/file.html",
                    body="<html>hello</html>",
                    content_type="text/html",
                )

            mock_logger.error.assert_called_once()
            assert "Error saving file to S3 at path/file.html" in mock_logger.error.call_args[0][0]

    def test_save_html_file_to_s3_generate_presigned_url_failure_logs_and_raises(self):
        with patch.object(s3_handler, "s3") as mock_s3, \
             patch.object(s3_handler, "logger") as mock_logger, \
             patch.object(s3_handler, "get_s3_bucket_name", return_value="my-test-bucket"):

            mock_s3.generate_presigned_url.side_effect = Exception("presign error")

            with pytest.raises(Exception, match="presign error"):
                s3_handler.save_html_file_to_s3(
                    key="path/file.html",
                    body="<html>hello</html>",
                    content_type="text/html",
                )

            mock_s3.put_object.assert_called_once_with(
                Bucket="my-test-bucket",
                Key="path/file.html",
                Body="<html>hello</html>",
                ContentType="text/html",
            )
            mock_logger.error.assert_called_once()
            assert "Error saving file to S3 at path/file.html" in mock_logger.error.call_args[0][0]

    def test_save_html_file_to_s3_get_bucket_failure_propagates(self):
        with patch.object(s3_handler, "get_s3_bucket_name", side_effect=Exception("bucket error")), \
             patch.object(s3_handler, "s3") as mock_s3:

            with pytest.raises(Exception, match="bucket error"):
                s3_handler.save_html_file_to_s3(
                    key="path/file.html",
                    body="<html>hello</html>",
                    content_type="text/html",
                )

            mock_s3.put_object.assert_not_called()