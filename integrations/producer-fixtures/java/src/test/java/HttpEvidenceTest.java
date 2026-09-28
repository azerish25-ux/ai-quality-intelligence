import io.restassured.RestAssured;
import io.restassured.response.Response;
import org.junit.Test;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.charset.StandardCharsets;

/** Actual loopback HTTP exchanges; only synthetic fixture data is ever sent. */
public class HttpEvidenceTest {
  private Response exchange(String name, String route) throws Exception {
    Response response = RestAssured.given().get("http://127.0.0.1:8779" + route);
    Path output = Path.of(System.getenv("PRODUCER_OUTPUT"), "java-" + name + ".json");
    String evidence = "{\"method\":\"GET\",\"route\":\"http://127.0.0.1:8779" + route + "\",\"status\":" + response.statusCode() + ",\"request\":{\"method\":\"GET\",\"url\":\"http://127.0.0.1:8779" + route + "\"},"
      + "\"response\":{\"status\":" + response.statusCode() + ",\"body_omitted\":true},"
      + "\"test_identity\":\"HttpEvidenceTest::" + name + "\",\"assertion\":\"expected status 200\"}";
    Files.writeString(output, evidence, StandardCharsets.UTF_8);
    return response;
  }
  @Test public void passingControl() throws Exception { exchange("passingControl", "/ok").then().statusCode(200); }
  @Test public void controlledFailure() throws Exception { exchange("controlledFailure", "/down").then().statusCode(200); }
}
